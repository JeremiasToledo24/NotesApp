# NotesApp: Arquitectura Cloud en AWS, Separacion de Ambientes, Almacenamiento S3 y Flujo de Desarrollo

## Resumen Ejecutivo

NotesApp es una solucion integral que implementa una arquitectura cloud-native en Amazon Web Services (AWS) para un backend desacoplado desarrollado en FastAPI, MySQL en Amazon RDS y almacenamiento de objetos en Amazon S3. El proyecto fue disenado bajo cuatro pilares fundamentales:

1. **Aislamiento Estricto de Ambientes**: Coexistencia de ambientes de Produccion (PROD) y Desarrollo (DEV) con segregacion logica tanto en bases de datos relacionales (RBAC a nivel de esquema MySQL) como en almacenamiento de objetos (particionado de prefijos en S3).
2. **Seguridad por Diseno**: Base de datos desplegada en subredes privadas sin asignacion de IP publica, filtrado de red mediante identificadores de Security Groups cruzados, acceso administrativo mediante tuneles SSH cifrados y gestion de credenciales cloud mediante Roles IAM de instancia sin claves estaticas en disco.
3. **Almacenamiento Desacoplado y Privado**: Bucket de Amazon S3 100% privado con bloqueo de acceso publico activo y cifrado en reposo SSE-S3. La descarga y visualizacion de archivos adjuntos se realiza mediante URLs prefirmadas temporales (Presigned URLs) con firma criptografica HMAC-SHA256 (SigV4).
4. **Costo Cero ($0.00 USD)**: Toda la infraestructura fue dimensionada y operada dentro de los limites de la Capa Gratuita (AWS Free Tier), implementando procedimientos de suspension programada de instancias de computo y bases de datos para evitar cargos no deseados.

---

## 1. Arquitectura e Infraestructura Cloud en AWS

La infraestructura se encuentra desplegada en la region `us-east-2` (Ohio) utilizando la CLI oficial de AWS (`aws-cli`) y scripts de aprovisionamiento automatizados.

```
                      +-----------------------------------------------------------------------------+
                      |                            VPC de AWS (us-east-2)                           |
                      |                                                                             |
                      |   +---------------------------------------------------------------------+   |
                      |   |                           Subred Publica                            |   |
                      |   |                                                                     |   |
                      |   |   +-------------------------------------------------------------+   |   |
                      |   |   |              Instancia EC2 (Amazon Linux 2023)              |   |   |
[ Internet ] -------->|---|-->|              Tipo: t3.micro | Tag: notesapp-server          |   |   |
 (HTTP 80 / 8000)     |   |   |              Rol IAM: NotesApp-EC2-S3-Role                  |   |   |
                      |   |   |                                                             |   |   |
[ Desarrollador ] --->|---|-->|  - Puerto 80:   notesapp-prod.service                       |   |   |
 (SSH 22)             |   |   |  - Puerto 8000: notesapp-dev.service                        |   |   |
                      |   |   +------------------------------|------------------------------+   |   |
                      |   +----------------------------------|----------------------------------+   |
                      |                                      |                                      |
                      |                 +--------------------+--------------------+                 |
                      |                 | (Trafico MySQL 3306)                    | (IAM SigV4 / SDK)
                      |                 v                                         v                 |
                      |   +-------------------------------------+   +---------------------------+   |
                      |   |           Subred Privada            |   |         Amazon S3         |   |
                      |   |                                     |   |   (notesapp-storage)      |   |
                      |   |   +-----------------------------+   |   |                           |   |
                      |   |   |  Amazon RDS MySQL 8.4       |   |   | - Bloqueo Publico: Activo |   |
                      |   |   |  Tipo: db.t3.micro          |   |   | - Cifrado: SSE-S3 AES256  |   |
                      |   |   |  Acceso Publico: NO         |   |   |                           |   |
                      |   |   |                             |   |   | Prefijos:                 |   |
                      |   |   |  - Esquema: notesdb_prod    |   |   |  * production/            |   |
                      |   |   |  - Esquema: notesdb_dev     |   |   |  * development/           |   |
                      |   |   +-----------------------------+   |   +---------------------------+   |
                      |   +-------------------------------------+                 ^                 |
                      +-----------------------------------------------------------|-----------------+
                                                                                  |
                                            (Descarga directa via Presigned URL)  |
[ Navegador / Cliente ] <=========================================================+
```

### 1.1 Red y Grupos de Seguridad (Security Groups)

El modelo de red implementa el principio de minimo privilegio mediante reglas cruzadas:

- **Security Group de EC2 (`notesapp-ec2-sg`)**:
  - Regla de entrada: TCP puerto 22 (SSH) para administracion remota y tunelizado.
  - Regla de entrada: TCP puerto 80 (HTTP) para el trafico web de Produccion.
  - Regla de entrada: TCP puerto 8000 (HTTP) para pruebas del ambiente de Desarrollo.
- **Security Group de RDS (`notesapp-rds-sg`)**:
  - Regla de entrada: TCP puerto 3306 (MySQL), autorizada unicamente referenciando el `GroupId` del Security Group de EC2 (`sg-0f6ff1140f0b425f6`).
  - Sin exposicion a Internet: no existe regla de acceso desde `0.0.0.0/0`.

### 1.2 Capa de Computo (Amazon EC2)

- **Instancia**: `t3.micro` con Amazon Linux 2023.
- **Almacenamiento**: Volumen EBS GP3 de 8 GB con cifrado habilitado.
- **Identidad Cloud (IAM Profile)**: La instancia tiene asignado el perfil `NotesApp-EC2-S3-Profile`, vinculado al rol `NotesApp-EC2-S3-Role`. Esto permite que `boto3` adquiera credenciales temporales rotativas mediante el servicio de metadatos (IMDSv2) sin almacenar llaves de acceso en archivos de texto.
- **Gestion de Procesos**: Servicios `systemd` para supervision y auto-reinicio:
  - `notesapp-prod.service`: Administra el proceso de Produccion en el puerto 80.
  - `notesapp-dev.service`: Administra el proceso de Desarrollo en el puerto 8000.
- **Entorno Virtual**: Python con virtualenv dedicado en `/opt/notesapp/venv`.

### 1.3 Capa de Datos Relacionales (Amazon RDS)

- **Motor**: MySQL 8.4 Community Edition.
- **Clase de Instancia**: `db.t3.micro` con 20 GB de almacenamiento GP2.
- **Topologia**: DB Subnet Group multi-AZ en subredes estrictamente privadas sin direccion IP publica.

### 1.4 Capa de Almacenamiento de Objetos (Amazon S3)

- **Bucket**: `notesapp-storage-jeremias` en la region `us-east-2`.
- **Politica de Seguridad**:
  - `BlockPublicAcls=true`, `IgnorePublicAcls=true`, `BlockPublicPolicy=true`, `RestrictPublicBuckets=true`.
  - Cifrado en reposo por defecto habilitado con algoritmo `AES256` (SSE-S3).
- **Control de Acceso**:
  - Acceso directo denegado por defecto (HTTP 403 Forbidden ante cualquier peticion anonima o sin firma).
  - Acceso temporal concedido exclusivamente mediante URLs prefirmadas generadas por el backend con vencimiento de 900 segundos (15 minutos).

---

## 2. Arquitectura de Software y Separacion de Ambientes

La aplicacion backend fue desarrollada con **FastAPI**, conexion directa mediante **PyMySQL** y el SDK oficial **Boto3**.

### 2.1 Modelo Dual en Instancia Unica (Optimizacion Free Tier)

Para evitar provisionar recursos duplicados que excedan las 750 horas mensuales de la capa gratuita, se implemento una particion logica completa entre Produccion y Desarrollo:

| Componente | Ambiente de Produccion | Ambiente de Desarrollo |
| :--- | :--- | :--- |
| **Servicio Systemd** | `notesapp-prod.service` | `notesapp-dev.service` |
| **Puerto de Escucha** | Puerto 80 (HTTP) | Puerto 8000 (HTTP) |
| **Directorio de Trabajo** | `/opt/notesapp/prod` | `/opt/notesapp/dev` |
| **Base de Datos (RDS)** | `notesdb_prod` | `notesdb_dev` |
| **Usuario de Base de Datos** | `prod_app` (DML restringido) | `jere_dev` (Aislado de prod) |
| **Prefijo de Almacenamiento S3** | `production/` | `development/` |
| **Archivo de Configuracion** | `/opt/notesapp/prod/.env` (`chmod 600`) | `/opt/notesapp/dev/.env` (`chmod 600`) |

### 2.2 Control de Acceso Basado en Roles (RBAC) y Prueba de Intrusion

Para certificar que una prueba o error en el entorno de desarrollo no pueda alterar los datos productivos, se aplicaron privilegios minimos:

```sql
-- Usuario de Produccion: Restringido a DML sobre su propio esquema
CREATE USER 'prod_app'@'%' IDENTIFIED BY '<PASSWORD_PROD>';
GRANT SELECT, INSERT, UPDATE, DELETE ON notesdb_prod.* TO 'prod_app'@'%';

-- Usuario de Desarrollo: Control total sobre DEV, revocado explicitamente de PROD
CREATE USER 'jere_dev'@'%' IDENTIFIED BY '<PASSWORD_DEV>';
GRANT ALL PRIVILEGES ON notesdb_dev.* TO 'jere_dev'@'%';
REVOKE ALL PRIVILEGES ON notesdb_prod.* FROM 'jere_dev'@'%';
FLUSH PRIVILEGES;
```

Resultado de la ejecucion del script de auditoria de penetracion (`test_security.py`):

```text
--- 1. Probando conexion de jere_dev a DEV (notesdb_dev) ---
Acceso permitido en DEV. Conectividad validada.

--- 2. Probando intento de intrusion de jere_dev a PROD (notesdb_prod) ---
SEGURIDAD CONFIRMADA: MySQL bloqueo a jere_dev de entrar a PROD:
   --> (1044, "Access denied for user 'jere_dev'@'%' to database 'notesdb_prod'")
```

---

## 3. Almacenamiento de Objetos en S3 y URLs Prefirmadas

### 3.1 Por que desacoplar el almacenamiento de la maquina virtual

Almacenar archivos subidos por usuarios (imagenes, documentos) en el sistema de archivos local de una maquina EC2 introduce problemas criticos:
- **Perdida de escalabilidad**: Impide que la aplicacion escale horizontalmente (Auto Scaling), ya que una instancia secundaria no tendria acceso a los archivos guardados en el disco local de la primera.
- **Riesgo de agotamiento de almacenamiento**: Los discos EBS tienen costo fijo por gigabyte aprovisionado y pueden llenarse, degradando el sistema operativo.
- **Sobrecarga de ancho de banda**: El servidor de aplicaciones gastaria memoria y ciclos de CPU enviando archivos estaticos a los clientes.

### 3.2 Flujo de Datos con Presigned URLs

Para mantener el bucket 100% privado y optimizar el rendimiento, se utiliza el patron de URLs prefirmadas:

1. **Subida**:
   - El cliente envia la nota y el archivo adjunto mediante un formulario `multipart/form-data` al backend FastAPI.
   - La aplicacion sanitiza el nombre del archivo, le antepone un identificador UUID unico y lo sube al bucket S3 bajo el prefijo correspondiente (`production/` o `development/`).
   - El backend guarda en MySQL el titulo, contenido, `file_key` (ruta en S3) y `file_name` (nombre original).
2. **Lectura y Descarga**:
   - Al consultar las notas (`GET /api/notes` o visualizacion web en `/`), el backend solicita a Boto3 la generacion de una URL prefirmada para cada archivo adjunto.
   - Boto3 calcula una firma criptografica HMAC-SHA256 (SigV4) utilizando el rol IAM de la maquina y le asigna una expiracion de 15 minutos (900 segundos).
   - El navegador web del usuario descarga la imagen o documento directamente desde Amazon S3, sin pasar por la instancia EC2.
   - Una vez transcurridos los 15 minutos, la URL queda invalidada automaticamente por AWS.

### 3.3 Verificacion de Seguridad del Bucket

Cualquier peticion directa a los objetos almacenados en el bucket sin parametros de prefirma autorizados es rechazada de forma inmediata:

```bash
$ curl -s -I https://notesapp-storage-jeremias.s3.us-east-2.amazonaws.com/production/0657b0da_requirements.txt
HTTP/1.1 403 Forbidden
x-amz-bucket-region: us-east-2
```

---

## 4. Flujo de Trabajo del Desarrollador y DevOps

El flujo de trabajo permite al programador modificar el codigo en su estacion de trabajo local con recarga en vivo sin exponer la nube de forma vulnerable.

```
[ Equipo del Desarrollador ]
  |
  +---> FastAPI Local (uvicorn app:app --reload --port 8000)
  |        |
  |        v (Conexion SQL a 127.0.0.1:3307)
  +---> Tunel SSH Local (ssh -N -L 3307:RDS_ENDPOINT:3306)
           |
           v (Canal cifrado puerto 22)
[ Instancia EC2 de AWS ]
           |
           v (Red interna privada 3306)
[ Amazon RDS (notesdb_dev) ]
```

### 4.1 Scripts de Automatizacion Operativa

Se desarrollaron scripts especificos para Windows PowerShell que estandarizan las tareas cotidianas:

1. **Apertura de Tunel Seguro (`start-db-tunnel.ps1`)**:
   Verifica el puerto local `3307` y establece un tunel SSH en segundo plano hacia el endpoint privado de RDS:
   ```powershell
   $tunnelParam = "$($LOCAL_PORT):$($RDS_ENDPOINT):$($REMOTE_PORT)"
   $sshCommand = "ssh -i '$KEY_FILE' -o StrictHostKeyChecking=no -N -L $tunnelParam ec2-user@$EC2_IP"
   Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", "$sshCommand" -WindowStyle Minimized
   ```

2. **Ejecucion Local con Hot-Reload (`start-dev.ps1`)**:
   Verifica el entorno virtual local de Python, instala dependencias si es necesario y lanza Uvicorn en modo recarga automatica sobre el puerto 8000.

3. **Despliegue Continuo a la Nube (`deploy-to-aws.ps1`)**:
   Transfiere `app.py`, `requirements.txt` y `deploy_environments.sh` mediante SCP, aplica las migraciones y actualiza los servicios systemd en la instancia remota:
   ```powershell
   scp -i $KEY_FILE -o StrictHostKeyChecking=no "$PSScriptRoot\app.py" "ec2-user@${EC2_IP}:/tmp/app.py"
   scp -i $KEY_FILE -o StrictHostKeyChecking=no "$PSScriptRoot\requirements.txt" "ec2-user@${EC2_IP}:/tmp/requirements.txt"
   scp -i $KEY_FILE -o StrictHostKeyChecking=no "$PSScriptRoot\deploy_environments.sh" "ec2-user@${EC2_IP}:/tmp/deploy_environments.sh"
   ssh -i $KEY_FILE -o StrictHostKeyChecking=no "ec2-user@${EC2_IP}" "sudo bash /tmp/deploy_environments.sh"
   ```

4. **Limpieza Total de Recursos (`cleanup.ps1`)**:
   Script de desmantelamiento controlado que permite eliminar de manera ordenada las instancias EC2, RDS, grupos de subredes y reglas de seguridad para retornar la cuenta a costo cero.

---

## 5. Bitacora de Construccion y Evolucion del Proyecto

A continuacion se documenta de forma cronologica el proceso tecnico de diseno, toma de decisiones, dificultades superadas y lecciones aprendidas a lo largo del desarrollo:

### Hito 1: Diseno Inicial y Prototipo Local
- **Objetivo**: Crear una aplicacion de notas rapida, moderna y ligera con FastAPI y MySQL.
- **Desarrollo**: Se creo el modelo de datos basico (`id`, `title`, `content`, `created_at`) y endpoints REST asincronos.
- **Leccion Aprendida**: Se identifico la necesidad de estructurar la lectura de variables de entorno desde el primer dia para permitir que el mismo codigo pudiera ejecutarse tanto en local como en la nube sin modificaciones.

### Hito 2: Despliegue de Infraestructura Cloud en AWS
- **Objetivo**: Trasladar la solucion a la nube respetando las mejores practicas de seguridad en redes.
- **Desarrollo**:
  - Creacion del par de claves SSH (`notes-api-key.pem`).
  - Creacion de los Security Groups cruzados: `notesapp-ec2-sg` (permite trafico web y SSH) y `notesapp-rds-sg` (autoriza trafico 3306 unicamente originado en el Security Group de EC2).
  - Aprovisionamiento de la instancia EC2 `t3.micro` y de la base de datos Amazon RDS `db.t3.micro` en subredes privadas.
- **Dificultad Tecnica**: RDS tardaba varios minutos en pasar de `creating` a `available`. Se establecieron mecanismos de consulta automatizada via CLI para monitorear el estado sin incurrir en bucles de sondeo ciego.

### Hito 3: La Decision de Arquitectura: Separacion de Ambientes vs FinOps
- **Dilema**: En un entorno corporativo formal se provisionan cuentas o instancias de RDS separadas para Produccion y Desarrollo. Sin embargo, en el AWS Free Tier tener dos instancias de RDS activas consumiria el doble de horas (1500 horas mensuales vs las 750 gratuitas), generando cargos en la tarjeta de credito.
- **Solucion Elegida**: Separacion logica estricta sobre la misma instancia RDS:
  - Dos esquemas independientes: `notesdb_prod` y `notesdb_dev`.
  - Dos usuarios MySQL con privilegios RBAC: `prod_app` (restringido a DML en prod) y `jere_dev` (con acceso total a dev y acceso revocado a prod).
  - Dos servicios `systemd` en EC2 corriendo en puertos diferenciados (80 y 8000).
- **Validacion**: Se desarrollo el script `test_security.py` para simular un ataque de escalada de privilegios, confirmando que MySQL deniega el acceso a `jere_dev` si intenta consultar la base productiva.

### Hito 4: Flujo de Trabajo Local Seguro (El Patron Tunel SSH)
- **Problema**: Inicialmente se considero exponer el puerto 8000 de desarrollo a Internet. El equipo cuestiono esta decision: abrir puertos de desarrollo a la red publica expone vulnerabilidades innecesarias.
- **Solucion**: Se decidio que el ambiente de desarrollo para el trabajo diario debia correr en la maquina local del programador con recarga automatica (`--reload`), conectandose a la base `notesdb_dev` en AWS mediante un tunel SSH seguro (`127.0.0.1:3307 -> EC2 -> RDS:3306`).
- **Ajuste en PowerShell**: Durante el desarrollo en Windows se presentaron peculiaridades en la sintaxis de PowerShell: la concatenacion `$RDS_ENDPOINT:` generaba errores de sintaxis al ser interpretada como una letra de unidad de disco. Se refactorizo a `"$($RDS_ENDPOINT):$PORT"`, y se utilizo `Start-Process` con `-WindowStyle Minimized` para que el tunel persista en segundo plano sin bloquear la terminal activa.

### Hito 5: Desacoplamiento de Almacenamiento con Amazon S3
- **Problema**: La aplicacion necesitaba permitir a los usuarios adjuntar archivos (imagenes, documentos). Guardar los archivos en el disco de la maquina EC2 violaba los principios de arquitectura sin estado (stateless compute).
- **Solucion**:
  - Se aprovisiono el bucket privado `notesapp-storage-jeremias` en `us-east-2` con Bloqueo de Acceso Publico total y cifrado SSE-S3.
  - Se creo el rol IAM `NotesApp-EC2-S3-Role` con politicas de minimo privilegio (`s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, `s3:ListBucket`) y se asocio a la instancia EC2 mediante un Instance Profile. Esto evito almacenar llaves de acceso en el servidor.
  - Se modifico `app.py` para recibir formularios multipart, particionar los archivos por ambiente (`production/` y `development/`) y servir los adjuntos mediante URLs prefirmadas (Presigned URLs) con expiracion de 15 minutos.
- **Incidencia Tecnica y Resolucion**: Durante las primeras pruebas de URLs prefirmadas, S3 devolvia `HTTP 307 Temporary Redirect` seguido de un error `SignatureDoesNotMatch`. Esto ocurria porque Boto3 utilizaba por defecto el endpoint global `s3.amazonaws.com` en lugar del endpoint regional. Al redirigir la peticion, el encabezado `Host` cambiaba y la firma criptografica HMAC se invalidaba. La solucion consistio en configurar explicitamente `endpoint_url=f"https://s3.{AWS_REGION}.amazonaws.com"` y `signature_version="s3v4"`, permitiendo descargas directas con codigo `200 OK`.

### Hito 6: Auditoria de Seguridad, Gestion Presupuestaria y Publicacion
- **Auditoria de Secretos**: Se reviso exhaustivamente el repositorio antes de la publicacion para garantizar que ninguna clave privada (`.pem`), contrasena de base de datos ni variable de entorno sensible (`.env`) pudiera ser rastreada por Git. Se configuro `.gitignore` con exclusiones estrictas.
- **Politica de FinOps**: Para garantizar el cumplimiento de la meta de costo cero ($0.00 USD), se crearon rutinas de detencion de computo (`aws ec2 stop-instances` y `aws rds stop-db-instance`) para pausar los recursos fuera de las sesiones de prueba.

---

## 6. Gestion del Ciclo de Vida y Detencion de Recursos

Para garantizar que no exista consumo de horas de computo ni cargos residuales fuera del horario de laboratorio, se define el procedimiento de suspension:

### 6.1 Detencion de Instancias (Preservacion de Datos a Costo Cero)

```powershell
# Detener instancia EC2
aws ec2 stop-instances --instance-ids i-0e42216b1b5bc3d40 --region us-east-2

# Detener base de datos RDS
aws rds stop-db-instance --db-instance-identifier notes-api-db --region us-east-2
```

- Las maquinas pasan al estado `stopped`.
- El costo de computo se detiene inmediatamente.
- Los datos en el volumen EBS, en la base MySQL y en el bucket S3 quedan preservados de manera intacta.

### 6.2 Reactivacion de la Infraestructura

Para reiniciar las actividades de prueba:

```powershell
aws rds start-db-instance --db-instance-identifier notes-api-db --region us-east-2
aws ec2 start-instances --instance-ids i-0e42216b1b5bc3d40 --region us-east-2
```

### 6.3 Destruccion Definitiva (Teardown)

Si se desea eliminar la totalidad de la infraestructura y dependencias creadas:

```powershell
.\cleanup.ps1
```

---

## 7. Conclusiones y Competencias Tecnicas Demostradas

El desarrollo integral de este proyecto refleja competencias practicas en areas criticas de la ingenieria de software y la nube:

- **Cloud Architecture**: Segmentacion de redes VPC, diseno de subredes publicas/privadas, reglas de firewall con Security Groups referenciados y almacenamiento de objetos en Amazon S3.
- **Identidad y Seguridad en AWS**: Implementacion de Roles IAM e Instance Profiles para computo sin claves estaticas, politicas de minimo privilegio, cifrado en reposo (EBS GP3 y S3 SSE-S3) y proteccion de datos mediante URLs prefirmadas SigV4.
- **Ingenieria de Backend**: Desarrollo con FastAPI, soporte de peticiones multipart asincronas, integracion con el SDK Boto3 y modelado de datos relacionales en MySQL.
- **DevOps y Automatizacion**: Orquestacion de servicios con systemd en Amazon Linux 2023, gestion de despliegue continuo mediante SSH/SCP, scripting en Windows PowerShell y tunelizado seguro de bases de datos.
- **FinOps y Gestion Presupuestaria**: Optimizacion arquitectonica para operar sistemas multi-ambiente dentro de la Capa Gratuita ($0.00 USD) sin generar costos imprevistos.
