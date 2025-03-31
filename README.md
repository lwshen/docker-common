# Docker Common

![LICENSE](https://img.shields.io/github/license/lwshen/docker-common?style=flat)

## Images

### [jre8](jre8/)

```
docker pull shenlw/jre:8
```

### [jdk8](jdk/8/)

```
docker pull shenlw/jdk:8
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/jdk:8
```

### [jdk11](jdk/11/)

```
docker pull shenlw/jdk:11
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/jdk:11
```

### [jdk17](jdk/17/)

```
docker pull shenlw/jdk:17
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/jdk:17
```

### [jdk21](jdk/21/)

```
docker pull shenlw/jdk:21
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/jdk:21
```

### [maven](maven/)

#### with JDK8

```
docker pull shenlw/maven:3-jdk-8
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/maven:3-jdk-8
```

#### with JDK11

```
docker pull shenlw/maven:3-jdk-11
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/maven:3-jdk-11
```

#### with JDK17

```
docker pull shenlw/maven:3-jdk-17
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/maven:3-jdk-17
```

#### with JDK21

```
docker pull shenlw/maven:3-jdk-21
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/maven:3-jdk-21
```

### [mvnd](mvnd/)

#### with JDK8

```
docker pull shenlw/mvnd:0-jdk-8
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/mvnd:0-jdk-8
```

#### with JDK11

```
docker pull shenlw/mvnd:0-jdk-11
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/mvnd:0-jdk-11
```

#### with JDK17

```
docker pull shenlw/mvnd:0-jdk-17
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/mvnd:0-jdk-17
```

#### with JDK21

```
docker pull shenlw/mvnd:0-jdk-21
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/mvnd:0-jdk-21
```

### [code](code/)

Environment with JDK8, JDK11, JDK17 and maven. Use `j8`, `j11`, `j17`, `j21` to switch JDK environment.

```
docker pull shenlw/code:latest
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/code:latest
```

### [ubuntu-playground](ubuntu-playground/)

Ubuntu Playground (NO GUI) is a place where you can play with ubuntu command.

```
docker pull shenlw/ubuntu-playground:latest
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/ubuntu-playground:latest
```

### [ubuntu-ngrok](ubuntu-ngrok/)

A container that provides SSH access through ngrok tunneling.

```
docker pull shenlw/ubuntu-ngrok:latest
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/ubuntu-ngrok:latest
```

#### Usage

```bash
docker run -d \
  -e SSH_PUBLIC_KEY="your_ssh_public_key" \
  -e NGROK_AUTH_TOKEN="your_ngrok_auth_token" \
  shenlw/ubuntu-ngrok
```

### [ubuntu-ngrok](ubuntu-cpolar/)

A container that provides SSH access through [cpolar](https://www.cpolar.com/) tunneling.

```
docker pull shenlw/ubuntu-cpolar:latest
```

```
docker pull registry.cn-shanghai.aliyuncs.com/lwshen/ubuntu-cpolar:latest
```

#### Usage

```bash
docker run -d \
  -e SSH_PUBLIC_KEY="your_ssh_public_key" \
  -e CPOLAR_AUTH_TOKEN="your_ngrok_auth_token" \
  -e CPOLAR_REGION="us" \
  shenlw/ubuntu-cpolar
```
