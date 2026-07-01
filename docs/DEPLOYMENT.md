# Deployment Guide

**Last Updated:** 2025-11-18

## Overview

This guide covers deploying Scribe in various environments, from single-user workstations to multi-user server deployments.

## Deployment Scenarios

### Single-User Workstation

**Best for:**
- Individual developers
- Content creators
- Small teams (< 5 users)

**Requirements:**
- NVIDIA GPU (optional but recommended)
- Python 3.10+
- FFmpeg
- 50GB+ free disk space

**Setup:**
```bash
# Clone repository
git clone https://github.com/blisspixel/scribe.git
cd scribe

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -e .

# Configure (recommended)
# Run the polished first-run wizard (review step, OBS preflight verification, optional Quick Record launcher)
python -m scribe init
# or after uv sync: uv run scribe init
# Edit .env with API keys
```

**Usage:**
```bash
scribe transcribe meeting.mp4
```

### Shared Server (Multi-User)

**Best for:**
- Teams (5-50 users)
- Shared GPU resources
- Centralized processing

**Requirements:**
- High-end GPU (RTX 4090 recommended)
- 32GB+ RAM
- 500GB+ SSD storage
- Linux server (Ubuntu 22.04 LTS recommended)

**Setup:**


```bash
# Install system dependencies
sudo apt update
sudo apt install python3.10 python3-pip ffmpeg git

# Install CUDA (if using GPU)
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install cuda-toolkit-12-4

# Clone and install Scribe
git clone https://github.com/blisspixel/scribe.git
cd scribe
python3 -m venv venv
source venv/bin/activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
pip install -e .

# Create shared output directory
sudo mkdir -p /shared/scribe/output
sudo chown -R $USER:users /shared/scribe
chmod 775 /shared/scribe/output

# Configure
cp .env.example .env
# Edit .env
export SCRIBE_OUTPUT_FOLDER=/shared/scribe/output
```

**User Access:**
```bash
# Add users to group
sudo usermod -a -G users username

# Each user activates environment
source /path/to/scribe/venv/bin/activate
scribe transcribe file.mp4
```

**Resource Management:**
- Use GPU resource manager (automatic)
- Limit concurrent users (2-3 for single GPU)
- Monitor with `nvidia-smi`

### Docker Deployment

**Best for:**
- Containerized environments
- Reproducible deployments
- Cloud deployments

**Dockerfile:**
```dockerfile
FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application
COPY . /app

# Install Python dependencies
RUN pip3 install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
RUN pip3 install --no-cache-dir -r requirements.txt
RUN pip3 install --no-cache-dir -e .

# Create output directory
RUN mkdir -p /app/output

# Set environment variables
ENV SCRIBE_OUTPUT_FOLDER=/app/output
ENV PYTHONUNBUFFERED=1

# Run as non-root user
RUN useradd -m -u 1000 scribe
USER scribe

# Default command
CMD ["scribe", "--help"]
```

**Build and run:**
```bash
# Build image
docker build -t scribe:latest .

# Run with GPU
docker run --gpus all \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/.env:/app/.env \
  scribe:latest \
  scribe transcribe /app/output/meeting.mp4

# Run without GPU (API mode)
docker run \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/.env:/app/.env \
  scribe:latest \
  scribe transcribe /app/output/meeting.mp4 --method openai
```

**Docker Compose:**
```yaml
version: '3.8'

services:
  scribe:
    build: .
    image: scribe:latest
    volumes:
      - ./output:/app/output
      - ./.env:/app/.env
    environment:
      - SCRIBE_OUTPUT_FOLDER=/app/output
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

### Cloud Deployment (AWS)

**Best for:**
- Large-scale processing
- On-demand GPU access
- Distributed teams

**EC2 Instance Setup:**

1. **Launch GPU instance:**
   - Instance type: g5.xlarge or g5.2xlarge
   - AMI: Deep Learning AMI (Ubuntu 22.04)
   - Storage: 100GB+ EBS SSD

2. **Connect and setup:**
```bash
ssh -i key.pem ubuntu@instance-ip

# Clone and install
git clone https://github.com/blisspixel/scribe.git
cd scribe
source activate pytorch
pip install -r requirements.txt
pip install -e .

# Configure
cp .env.example .env
# Add API keys
```

3. **S3 Integration (optional):**
```bash
# Install AWS CLI
pip install awscli

# Configure
aws configure

# Upload results to S3
aws s3 cp output/ s3://bucket/scribe-output/ --recursive
```

**Cost Optimization:**
- Use Spot Instances for batch processing
- Stop instance when not in use
- Use S3 for long-term storage
- Consider Lambda for API-only mode

### Kubernetes Deployment

**Best for:**
- Enterprise deployments
- Auto-scaling
- High availability

**Deployment manifest:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: scribe
spec:
  replicas: 2
  selector:
    matchLabels:
      app: scribe
  template:
    metadata:
      labels:
        app: scribe
    spec:
      containers:
      - name: scribe
        image: scribe:latest
        resources:
          limits:
            nvidia.com/gpu: 1
            memory: "16Gi"
            cpu: "4"
          requests:
            nvidia.com/gpu: 1
            memory: "8Gi"
            cpu: "2"
        volumeMounts:
        - name: output
          mountPath: /app/output
        - name: config
          mountPath: /app/.env
          subPath: .env
        env:
        - name: SCRIBE_OUTPUT_FOLDER
          value: "/app/output"
      volumes:
      - name: output
        persistentVolumeClaim:
          claimName: scribe-output
      - name: config
        secret:
          secretName: scribe-config
```

**Service manifest:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: scribe-service
spec:
  selector:
    app: scribe
  ports:
  - port: 8000
    targetPort: 8000
  type: LoadBalancer
```

## Configuration Management

### Environment Variables

**Production .env:**
```env
# API Keys (use secrets management)
OPENAI_API_KEY=${OPENAI_API_KEY}
XAI_API_KEY=${XAI_API_KEY}

# Output
SCRIBE_OUTPUT_FOLDER=/shared/scribe/output

# Defaults
SCRIBE_DEFAULT_MODEL=large-v3
SCRIBE_DEFAULT_LANGUAGE=en

# Features
SCRIBE_ENABLE_NOTES=true
SCRIBE_ENABLE_MEME_BAKEOFF=false

# Terminal UI
SCRIBE_ANIMATIONS=off
SCRIBE_BANNER=off

# Download (URL transcription)
SCRIBE_DOWNLOAD_TIMEOUT=600
SCRIBE_KEEP_DOWNLOADS=false

# Logging
SCRIBE_LOG_LEVEL=INFO

# Performance
SCRIBE_MEME_QA_THRESHOLD=8.0
SCRIBE_MEME_QA_ATTEMPTS=3
```

### Secrets Management

**AWS Secrets Manager:**
```bash
# Store API key
aws secretsmanager create-secret \
  --name scribe/openai-api-key \
  --secret-string "sk-proj-..."

# Retrieve in application
aws secretsmanager get-secret-value \
  --secret-id scribe/openai-api-key \
  --query SecretString \
  --output text
```

**Kubernetes Secrets:**
```bash
# Create secret
kubectl create secret generic scribe-config \
  --from-literal=OPENAI_API_KEY=sk-proj-... \
  --from-literal=XAI_API_KEY=xai-...

# Use in deployment (see manifest above)
```

**Docker Secrets:**
```bash
# Create secret
echo "sk-proj-..." | docker secret create openai_api_key -

# Use in service
docker service create \
  --secret openai_api_key \
  --env OPENAI_API_KEY_FILE=/run/secrets/openai_api_key \
  scribe:latest
```

## Monitoring

### System Monitoring

**GPU Monitoring:**
```bash
# Real-time monitoring
watch -n 1 nvidia-smi

# Log to file
nvidia-smi dmon -s pucvmet -o T -f gpu_metrics.log
```

**Application Logs:**
```bash
# Tail logs
tail -f logs/scribe_*.log

# Search for errors
grep ERROR logs/scribe_*.log

# Monitor in real-time
tail -f logs/scribe_*.log | grep -E "ERROR|WARNING"
```

**Disk Usage:**
```bash
# Check output directory
du -sh /shared/scribe/output

# Monitor disk space
df -h

# Clean old files
find /shared/scribe/output -mtime +30 -delete
```

### Performance Monitoring

**Prometheus Metrics (Future):**
```yaml
# Example metrics
scribe_transcription_duration_seconds
scribe_transcription_speed_ratio
scribe_gpu_utilization_percent
scribe_api_requests_total
scribe_errors_total
```

**Custom Monitoring:**
```python
import time
import json

def log_metrics(operation, duration, success):
    metrics = {
        "timestamp": time.time(),
        "operation": operation,
        "duration": duration,
        "success": success
    }
    with open("metrics.jsonl", "a") as f:
        f.write(json.dumps(metrics) + "\n")
```

## Backup and Recovery

### Backup Strategy

**What to backup:**
- Configuration files (.env)
- Custom vocabulary files
- Output directory (transcripts, notes, memes)
- Performance metrics
- Logs (optional)

**Backup script:**
```bash
#!/bin/bash
BACKUP_DIR="/backup/scribe/$(date +%Y%m%d)"
mkdir -p $BACKUP_DIR

# Backup configuration
cp .env $BACKUP_DIR/

# Backup output
rsync -av --progress /shared/scribe/output/ $BACKUP_DIR/output/

# Backup metrics
cp ~/.scribe/performance_*.json $BACKUP_DIR/

# Compress
tar -czf $BACKUP_DIR.tar.gz $BACKUP_DIR
rm -rf $BACKUP_DIR

# Upload to S3 (optional)
aws s3 cp $BACKUP_DIR.tar.gz s3://bucket/backups/
```

**Automated backups:**
```bash
# Add to crontab
crontab -e

# Daily backup at 2 AM
0 2 * * * /path/to/backup.sh
```

### Disaster Recovery

**Recovery procedure:**
```bash
# 1. Restore from backup
tar -xzf backup_20250118.tar.gz

# 2. Restore configuration
cp backup_20250118/.env .env

# 3. Restore output
rsync -av backup_20250118/output/ /shared/scribe/output/

# 4. Restore metrics
cp backup_20250118/performance_*.json ~/.scribe/

# 5. Verify
scribe doctor
```

## Security

### API Key Security

**Best practices:**
- Never commit API keys to git
- Use environment variables or secrets management
- Rotate keys regularly
- Use separate keys for dev/prod
- Monitor API usage for anomalies

**Key rotation:**
```bash
# 1. Generate new key from provider
# 2. Update secrets
# 3. Test with new key
# 4. Revoke old key
```

### File Permissions

**Secure configuration:**
```bash
# Restrict .env file
chmod 600 .env

# Secure output directory
chmod 750 /shared/scribe/output

# Secure logs
chmod 640 logs/*.log
```

### Network Security

**Firewall rules:**
```bash
# Allow only necessary ports
sudo ufw allow 22/tcp  # SSH
sudo ufw allow 4455/tcp  # OBS WebSocket (if needed)
sudo ufw enable
```

**API access:**
- Use HTTPS only
- Implement rate limiting
- Monitor for abuse
- Use API key restrictions (if available)

## Scaling

### Horizontal Scaling

**Multiple GPU servers:**
```
Load Balancer
    │
    ├─── Server 1 (RTX 4090)
    ├─── Server 2 (RTX 4090)
    └─── Server 3 (RTX 4090)
```

**Queue-based processing:**
```python
# Producer
import redis
r = redis.Redis()
r.lpush('transcription_queue', '/path/to/audio.mp4')

# Consumer (on each server)
while True:
    file_path = r.brpop('transcription_queue')[1]
    transcribe(file_path)
```

### Vertical Scaling

**Upgrade GPU:**
- RTX 4070 → RTX 4080 (2x faster)
- RTX 4080 → RTX 4090 (1.5x faster)

**Add more GPUs:**
```python
# Use multiple GPUs (advanced)
import torch
torch.cuda.set_device(0)  # Use GPU 0
torch.cuda.set_device(1)  # Use GPU 1
```

## Maintenance

### Regular Tasks

**Daily:**
- Monitor disk space
- Check error logs
- Verify GPU health

**Weekly:**
- Clean old output files
- Review performance metrics
- Update dependencies (if needed)

**Monthly:**
- Backup configuration
- Review API usage and costs
- Update documentation

### Updates

**Update Scribe:**
```bash
cd scribe
git pull
pip install -r requirements.txt
pip install -e .

# Run tests
pytest

# Verify
scribe doctor
```

**Update dependencies:**
```bash
pip install --upgrade -r requirements.txt
```

## Troubleshooting Deployment

### Common Issues

**GPU not accessible in Docker:**
```bash
# Install nvidia-docker2
sudo apt install nvidia-docker2
sudo systemctl restart docker

# Test
docker run --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

**Permission denied errors:**
```bash
# Fix ownership
sudo chown -R $USER:$USER /shared/scribe

# Fix permissions
chmod -R 755 /shared/scribe
```

**Out of disk space:**
```bash
# Clean old files
find /shared/scribe/output -mtime +30 -delete

# Clean Docker
docker system prune -a
```

## Best Practices

1. **Use version control** for configuration
2. **Implement monitoring** from day one
3. **Automate backups** regularly
4. **Document changes** in deployment
5. **Test updates** in staging first
6. **Monitor costs** for cloud/API usage
7. **Secure API keys** properly
8. **Plan for scaling** early
9. **Keep dependencies updated**
10. **Have disaster recovery plan**

## Summary

Deployment options:
- **Workstation:** Simple, single-user
- **Shared Server:** Multi-user, centralized
- **Docker:** Containerized, reproducible
- **Cloud:** Scalable, on-demand
- **Kubernetes:** Enterprise, auto-scaling

Choose based on:
- Number of users
- Processing volume
- Budget
- Technical expertise
- Scaling requirements
