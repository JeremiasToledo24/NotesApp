# NotesApp: Arquitectura Cloud en AWS, Separacion de Ambientes y Flujo de Desarrollo

## Resumen Ejecutivo

NotesApp es una solucion integral que implementa una arquitectura cloud-native en Amazon Web Services (AWS) para un backend en FastAPI y MySQL. El proyecto fue disenado bajo tres pilares fundamentales:

1. **Aislamiento Estricto de Ambientes**: Coexistencia de ambientes de Produccion (PROD) y Desarrollo (DEV) con segregacion logica y control de acceso basado en roles (RBAC) a nivel de base de datos.
2. **Seguridad por Diseno**: Base de datos desplegada en subredes privadas sin exposicion publica a Internet, comunicacion interna filtrada por identificadores de grupos de seguridad cruzados y acceso seguro mediante tuneles SSH cifrados.
3. **Costo Cero ($0.00 USD)**: Toda la arquitectura fue aprovisionada y dimensionada para operar estrictamente dentro de la Capa Gratuita (AWS Free Tier), optimizando el consumo de horas de computo y almacenamiento sin generar costos inesperados.

---

## 1. Arquitectura e Infraestructura Cloud en AWS

La infraestructura fue desplegada en la region `us-east-2` (Ohio) utilizando la CLI oficial de AWS (`aws-cli`) y scripts de aprovisionamiento automatizados.

```
                      +-------------------------------------------------------------+
                      |                      VPC de AWS (us-east-2)                 |
                      |                                                             |
                      |   +-----------------------------------------------------+   |
                      |   |                 Subred Publica                      |   |
                      |   |                                                     |   |
                      |   |   +---------------------------------------------+   |   |
                      |   |   |        Instancia EC2 (Amazon Linux 2023)    |   |   |
[ Internet ] -------->|---|-->|        Tipo: t3.micro | Tag: notesapp-server|   |   |
 (HTTP 80 / 8000)     |   |   |                                             |   |   |
                      |   |   |  - Puerto 80:   notesapp-prod.service       |   |   |
[ Desarrollador ] --->|---|-->|  - Puerto 8000: notesapp-dev.service        |   |   |
 (SSH 22)             |   |   +---------------------------------------------+   |   |
                      |   +--------------------------|--------------------------+   |
                      |                              | (Trafico interno MySQL 3306) |
                      |                              v                              |
                      |   +-----------------------------------------------------+   |
                      |   |                 Subred Privada                      |   |
                      |   |                                                     |   |
                      |   |   +---------------------------------------------+   |   |
                      |   |   |         Amazon RDS MySQL 8.4 Community      |   |   |
                      |   |   |         Tipo: db.t3.micro | Tag: notesapp-db|   |   |
                      |   |   |         Acceso Publico: NO                  |   |   |
                      |   |   |                                             |   |   |
                      |   |   |  - Esquema: notesdb_prod                    |   |   |
                      |   |   |  - Esquema: notesdb_dev                     |   |   |
                      |   |   +---------------------------------------------+   |   |
                      |   +-----------------------------------------------------+   |
                      +-------------------------------------------------------------+
```

### 1.1 Red y Grupos de Seguridad (Security Groups)

El modelo de red implementa el principio de minimo privilegio mediante reglas cruzadas:

- **Security Group de EC2 (`notesapp-ec2-sg`)**:
  - Regla de entrada: TCP puerto 22 (SSH) para administracion remota y tunelizado.
  - Regla de entrada: TCP puerto 80 (HTTP) para el trafico de Produccion.
  - Regla de entrada: TCP puerto 8000 (HTTP) para pruebas del ambiente de Desarrollo.
- **Security Group de RDS (`notesapp-rds-sg`)**:
  - Regla de entrada: TCP puerto 3306 (MySQL), autorizada unicamente referenciando el `GroupId` del Security Group de EC2.
  - No existe ninguna regla que permita el acceso desde direcciones IP publicas de Internet (`0.0.0.0/0`).

### 1.2 Capa de Computo (Amazon EC2)

- **Instancia**: `t3.micro` con sistema operativo Amazon Linux 2023.
- **Almacenamiento**: Volumen EBS GP3 de 8 GB con cifrado habilitado.
- **Gestion de Servicios**: Implementacion de `systemd` para supervision y reinicio automatico:
  - `notesapp-prod.service`: Administra el proceso de Produccion en el puerto 80.
  - `notesapp-dev.service`: Administra el proceso de Desarrollo en el puerto 8000.
- **Entorno Virtual**: Python 3.13 con virtualenv dedicado en `/opt/notesapp/venv`.

### 1.3 Capa de Datos (Amazon RDS)

- **Motor**: MySQL 8.4 Community Edition.
- **Clase de Instancia**: `db.t3.micro` con 20 GB de almacenamiento GP2.
- **Topologia**: DB Subnet Group desplegado en subredes privadas multi-AZ para cumplimiento de estandares de disponibilidad, sin asignacion de IP publica.

---

## 2. Arquitectura de Software y Separacion de Ambientes

La aplicacion backend fue desarrollada con **FastAPI** y conexion directa mediante **PyMySQL**.

### 2.1 Modelo Dual en Instancia Unica (Optimizacion Free Tier)

Para evitar duplicar instancias fisicas de base de datos (lo cual superaria el limite de 750 horas mensuales de la capa gratuita), se implemento segregacion logica mediante esquemas independientes:

| Caracteristica | Ambiente de Produccion | Ambiente de Desarrollo |
| :--- | :--- | :--- |
| **Servicio Systemd** | `notesapp-prod.service` | `notesapp-dev.service` |
| **Puerto HTTP** | 80 | 8000 |
| **Directorio en Servidor** | `/opt/notesapp/prod` | `/opt/notesapp/dev` |
| **Base de Datos** | `notesdb_prod` | `notesdb_dev` |
| **Usuario MySQL** | `prod_app` | `jere_dev` |
| **Variables de Entorno** | `.env` independiente (`chmod 600`) | `.env` independiente (`chmod 600`) |

### 2.2 Control de Acceso Basado en Roles (RBAC) y Prueba de Intrusion

Para garantizar que un desarrollador o una prueba fallida en DEV nunca comprometa la integridad de Produccion, se configuraron privilegios diferenciados:

```sql
-- Usuario de Produccion: Restringido a DML sobre su esquema
CREATE USER 'prod_app'@'%' IDENTIFIED BY '<PASSWORD_PROD>';
GRANT SELECT, INSERT, UPDATE, DELETE ON notesdb_prod.* TO 'prod_app'@'%';

-- Usuario de Desarrollo: Control total sobre DEV, revocado explicitamente de PROD
CREATE USER 'jere_dev'@'%' IDENTIFIED BY '<PASSWORD_DEV>';
GRANT ALL PRIVILEGES ON notesdb_dev.* TO 'jere_dev'@'%';
REVOKE ALL PRIVILEGES ON notesdb_prod.* FROM 'jere_dev'@'%';
FLUSH PRIVILEGES;
```

Se ejecuto un script automatizado de validacion de penetracion (`test_security.py`) obteniendo el siguiente resultado en consola:

```text
--- 1. Probando conexion de jere_dev a DEV (notesdb_dev) ---
Acceso permitido en DEV. Conectividad validada.

--- 2. Probando intento de intrusion de jere_dev a PROD (notesdb_prod) ---
SEGURIDAD CONFIRMADA: MySQL bloqueo a jere_dev de entrar a PROD:
   --> (1044, "Access denied for user 'jere_dev'@'%' to database 'notesdb_prod'")
```

---

## 3. Flujo de Trabajo del Desarrollador

El flujo de trabajo permite al programador modificar el codigo en su entorno local con recarga en caliente sin alterar la nube de forma riesgosa.

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

### 3.1 Procedimiento de Trabajo Diario y Automatizacion

Para optimizar la rutina de desarrollo se crearon scripts de soporte que encapsulan las tareas operativas complejas. A continuacion se detallan las operaciones esenciales ejecutadas:

#### 1. Apertura del Tunel Seguro (`start-db-tunnel.ps1`)
Comprueba si el puerto local `3307` ya esta ocupado; si no lo esta, inicia una sesion SSH en segundo plano para reenviar el trafico hacia la base de datos privada en AWS:

```powershell
# Verificacion de puerto y apertura de tunel SSH seguro
$tunnelParam = "$($LOCAL_PORT):$($RDS_ENDPOINT):$($REMOTE_PORT)"
$sshCommand = "ssh -i '$KEY_FILE' -o StrictHostKeyChecking=no -N -L $tunnelParam ec2-user@$EC2_IP"

# Se ejecuta en ventana minimizada e independiente
Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", "$sshCommand" -WindowStyle Minimized
```

#### 2. Ejecucion Local con Hot-Reload (`start-dev.ps1`)
Verifica la existencia del entorno virtual de Python, instala dependencias si es necesario y lanza el servidor Uvicorn en modo recarga automatica:

```powershell
# Verificacion o creacion del entorno virtual local
if (-not (Test-Path $PYTHON_BIN)) {
    python -m venv $VENV_PATH
    & $PYTHON_BIN -m pip install -r requirements.txt
}

# Inicio del servidor con recarga en vivo
& $UVICORN_BIN app:app --reload --host 127.0.0.1 --port 8000
```

#### 3. Despliegue Continuo a la Nube (`deploy-to-aws.ps1`)
Transfiere el codigo fuente actualizado mediante SCP, ejecuta el script de aprovisionamiento en la instancia remota y valida el estado de los servicios:

```powershell
# Transferencia segura de artefactos
scp -i $KEY_FILE -o StrictHostKeyChecking=no app.py "ec2-user@${EC2_IP}:/tmp/app.py"
scp -i $KEY_FILE -o StrictHostKeyChecking=no deploy_environments.sh "ec2-user@${EC2_IP}:/tmp/deploy_environments.sh"

# Aplicacion remota de cambios en systemd
ssh -i $KEY_FILE -o StrictHostKeyChecking=no "ec2-user@${EC2_IP}" "sudo bash /tmp/deploy_environments.sh"

# Verificacion de diagnostico en vivo
$prodHealth = Invoke-RestMethod -Uri "http://${EC2_IP}/api/health"
$devHealth = Invoke-RestMethod -Uri "http://${EC2_IP}:8000/api/health"
```

#### 4. Limpieza Total de Recursos (`cleanup.ps1`)
Permite eliminar de manera programatica todos los elementos aprovisionados en AWS para garantizar que la cuenta vuelva a costo cero sin recursos huerfanos:

```powershell
# Terminacion de instancias de computo
aws ec2 terminate-instances --instance-ids $ec2Ids --region $Region

# Eliminacion de base de datos sin snapshots que generen costo de almacenamiento
aws rds delete-db-instance --db-instance-identifier $dbId --skip-final-snapshot --delete-automated-backups --region $Region

# Liberacion de grupos de subredes y security groups
aws rds delete-db-subnet-group --db-subnet-group-name $sng --region $Region
aws ec2 delete-security-group --group-name $sg --region $Region
```

---

## 4. Metodologia de Pair Programming y Asistencia con IA

Durante la ejecucion de este proyecto se adopto una metodologia estructurada de ingenieria asistida por inteligencia artificial, destacando las siguientes practicas:

### 4.1 Definicion de Reglas y Gobernanza de Costos
Al inicio del proyecto se establecieron directivas inmutables en el sistema de agentes (`AGENTS.md`):
- Restriccion estricta a la Capa Gratuita de AWS ($0.00 USD).
- Prohibicion de aprovisionar servicios no cubiertos o de alto costo.
- Requisito de aprobacion explicita del usuario previa a cualquier ejecucion o comando modificador.

### 4.2 Diseno Iterativo y Retroalimentacion Critica
- **Cuestionamiento de Decisiones de Arquitectura**: Cuando se propuso exponer publicamente el ambiente de desarrollo en el puerto 8000, el usuario cuestiono acertadamente la justificacion de tener DEV abierto a Internet en lugar de mantenerlo confinado a un entorno local. Esto condujo al diseno de la solucion con tunel SSH y desacoplamiento de puertos.
- **Modo de Planificacion Formal**: Cada fase requirio un artefacto de plan (`implementation_plan.md`) con analisis de riesgos, evaluacion de costos y confirmacion explicita del usuario.
- **Resolucion de Incidencias en Tiempo Real**:
  - Resolucion de colisiones de interpolacion en Windows PowerShell (`$var:` interpretado como unidad de almacenamiento).
  - Gestion del ciclo de vida de subprocesos SSH en segundo plano para evitar cierres prematuros por finalizacion de consola.
  - Migracion sin fallas de rutas de sistema (`/opt/notes-api` a `/opt/notesapp`) preservando los binarios del entorno virtual existente.

---

## 5. Gestion del Ciclo de Vida y Detencion de Recursos

Para garantizar que no exista consumo de computo cuando el laboratorio no esta en uso, se definio una estrategia de suspension de recursos:

### 5.1 Detencion de Instancias
- **Detener EC2**:
  ```powershell
  aws ec2 stop-instances --instance-ids i-0e42216b1b5bc3d40 --region us-east-2
  ```
  La maquina virtual pasa a estado `stopped`. El costo de computo se reduce a $0.00 USD. El almacenamiento EBS preserva el codigo y configuraciones.
- **Detener RDS**:
  ```powershell
  aws rds stop-db-instance --db-instance-identifier notes-api-db --region us-east-2
  ```
  El motor MySQL pasa a estado `stopped`. Los esquemas, tablas y registros se preservan en el almacenamiento asignado.

### 5.2 Reactivacion de la Infraestructura
Para reanudar las pruebas:
```powershell
aws rds start-db-instance --db-instance-identifier notes-api-db --region us-east-2
aws ec2 start-instances --instance-ids i-0e42216b1b5bc3d40 --region us-east-2
```

### 5.3 Destruccion Total (Teardown)
Si se desea eliminar la totalidad de los recursos provisionados sin dejar elementos residuales:
```powershell
.\cleanup.ps1
```

---

## 6. Conclusiones y Competencias Demostradas

El desarrollo de este proyecto evidencia competencias clave en:
- **Cloud Computing**: Aprovisionamiento seguro, segmentacion de subredes, VPCs y grupos de seguridad en AWS.
- **Backend Engineering**: Desarrollo de APIs asincronas con FastAPI, gestion de esquemas relacionales y diseno RBAC en MySQL.
- **DevOps y Automatizacion**: Orquestacion de servicios con systemd en Linux, scripting en PowerShell, tunelizado SSH y flujos de despliegue continuo.
- **Seguridad Operativa**: Mitigacion de fugas de secretos en Git, principio de minimo privilegio y auditoria de contraseñas.
- **Optimizacion Financiera (FinOps)**: Control riguroso de presupuestos y diseno de arquitecturas eficientes dentro del AWS Free Tier.
