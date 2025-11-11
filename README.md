# Docker Common

![LICENSE](https://img.shields.io/github/license/lwshen/docker-common?style=flat)

A collection of Docker images for development and operational environments. These images are designed to provide consistent and reliable environments for Java development, database operations, and tunneling services.

## Building Images Locally

To build any image locally:

```bash
cd <image-directory>
docker build -t <name>:<tag> .
```

For Maven and MVND images that use version arguments:

```bash
docker build --build-arg MAVEN_VERSION=3.9.9 -t maven:custom .
```

## Images

### Java

#### [jre8](jre8/)

```
docker pull shenlw/jre:8
```

#### [jdk8](jdk/8/)

```
docker pull shenlw/jdk:8
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/jdk:8
```

#### [jdk11](jdk/11/)

```
docker pull shenlw/jdk:11
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/jdk:11
```

#### [jdk17](jdk/17/)

```
docker pull shenlw/jdk:17
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/jdk:17
```

#### [jdk21](jdk/21/)

```
docker pull shenlw/jdk:21
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/jdk:21
```

#### [jdk25](jdk/25/)

```
docker pull shenlw/jdk:25
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/jdk:25
```

### Build Tools

#### [maven](maven/)

Maven images with different JDK versions:

- **JDK 8**: `docker pull shenlw/maven:3-jdk-8`
- **JDK 11**: `docker pull shenlw/maven:3-jdk-11`
- **JDK 17**: `docker pull shenlw/maven:3-jdk-17`
- **JDK 21**: `docker pull shenlw/maven:3-jdk-21`
- **JDK 25**: `docker pull shenlw/maven:3-jdk-25`

Also available on Aliyun registry:

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/maven:3-jdk-<version>
```

#### [mvnd](mvnd/)

Maven Daemon images with different JDK versions:

- **JDK 8**: `docker pull shenlw/mvnd:0-jdk-8`
- **JDK 11**: `docker pull shenlw/mvnd:0-jdk-11`
- **JDK 17**: `docker pull shenlw/mvnd:0-jdk-17`
- **JDK 21**: `docker pull shenlw/mvnd:0-jdk-21`
- **JDK 25**: `docker pull shenlw/mvnd:0-jdk-25`

Also available on Aliyun registry:

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/mvnd:0-jdk-<version>
```

### Development Environments

#### [code](code/)

Complete development environment with multiple JDK versions and Maven.

```
docker pull shenlw/code:latest
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/code:latest
```

Use `j8`, `j11`, `j17`, `j21`, or `j25` commands to switch JDK environment.

#### [ubuntu-playground](ubuntu-playground/)

Ubuntu Playground (NO GUI) for ubuntu command exploration.

```
docker pull shenlw/ubuntu-playground:latest
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/ubuntu-playground:latest
```

### Tunneling Solutions

#### [ubuntu-ngrok](ubuntu-ngrok/)

Container that provides SSH access through ngrok tunneling.

```
docker pull shenlw/ubuntu-ngrok:latest
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/ubuntu-ngrok:latest
```

**Usage:**

```bash
docker run -d \
  -e SSH_PUBLIC_KEY="your_ssh_public_key" \
  -e NGROK_AUTH_TOKEN="your_ngrok_auth_token" \
  shenlw/ubuntu-ngrok
```

#### [ubuntu-cpolar](ubuntu-cpolar/)

Container that provides SSH access through [cpolar](https://www.cpolar.com/) tunneling.

```
docker pull shenlw/ubuntu-cpolar:latest
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/ubuntu-cpolar:latest
```

**Usage:**

```bash
docker run -d \
  -e SSH_PUBLIC_KEY="your_ssh_public_key" \
  -e CPOLAR_AUTH_TOKEN="your_cpolar_auth_token" \
  -e CPOLAR_REGION="us" \
  shenlw/ubuntu-cpolar
```

### Database Tools

#### [postgres-backup-s3](postgres-backup-s3/)

Backup PostgreSQL databases to S3.

```
docker pull shenlw/postgres-backup-s3:latest
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/postgres-backup-s3:latest
```

#### [postgres-restore-s3](postgres-restore-s3/)

Restore PostgreSQL databases from S3 backups.

```
docker pull shenlw/postgres-restore-s3:latest
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/postgres-restore-s3:latest
```

#### [postgres-restore-file](postgres-restore-file/)

Restore PostgreSQL databases from local backup files.

```
docker pull shenlw/postgres-restore-file:latest
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/postgres-restore-file:latest
```

## Development

- Dockerfile linting: `hadolint <dockerfile-path>`
- Version management: Update constants.env for centralized version control
