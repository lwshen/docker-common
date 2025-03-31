# Ubuntu with Cpolar

A container that provides SSH access through [cpolar](https://www.cpolar.com/) tunneling.

## Usage


```bash
docker run -d \
  -e SSH_PUBLIC_KEY="your_ssh_public_key" \
  -e CPOLAR_AUTH_TOKEN="your_ngrok_auth_token" \
  -e CPOLAR_REGION="us" \
  shenlw/ubuntu-cpolar
```

## Environment Variables

- `SSH_PUBLIC_KEY`: Your SSH public key for authentication
- `CPOLAR_AUTH_TOKEN`: Your cpolar authentication token
- `CPOLAR_REGION`: Choose the region where the cpolar client will connect to host its tunnels. Default is 'us'.
