# Ubuntu with Ngrok

A container that provides SSH access through ngrok tunneling.

## Usage


```bash
docker run -d \
  -e SSH_PUBLIC_KEY="your_ssh_public_key" \
  -e NGROK_AUTH_TOKEN="your_ngrok_auth_token" \
  shenlw/ubuntu-ngrok
```

## Environment Variables

- `SSH_PUBLIC_KEY`: Your SSH public key for authentication
- `NGROK_AUTH_TOKEN`: Your ngrok authentication token
