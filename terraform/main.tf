# Concierge API - AWS Deployment
# Monce AI extraction memory & intelligence layer

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "eu-west-3" # Paris
}

variable "allowed_ips" {
  description = "IP addresses allowed for SSH/HTTPS access"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "key_name" {
  description = "SSH key pair name"
  type        = string
  default     = "vlm-extraction-key"
}

# Security Group - POC VPC
resource "aws_security_group" "concierge_sg" {
  name        = "concierge-api-sg"
  description = "Concierge API - HTTPS access"
  vpc_id      = "vpc-0c99f4b9ac1d073ad" # POC VPC

  # SSH from team IPs
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["31.32.0.77/32", "88.187.147.251/32", "37.65.169.46/32", "197.147.121.107/32", "199.36.158.100/32"]
    description = "SSH from team IPs"
  }

  # HTTPS from anywhere
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.allowed_ips
    description = "HTTPS"
  }

  # HTTP for certbot
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.allowed_ips
    description = "HTTP for certbot"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "concierge-api-sg"
    Project = "concierge-aws-monce-ai"
  }
}

# EC2 Instance
resource "aws_instance" "concierge_server" {
  ami                         = "ami-0f3f2cef1fc7d0edb" # Ubuntu 22.04 LTS eu-west-3
  instance_type               = "t3.small"              # 2 vCPU, 2GB RAM
  key_name                    = var.key_name
  associate_public_ip_address = true
  subnet_id                   = "subnet-06035ab0ffd8c92e6" # POC Public Subnet-a

  vpc_security_group_ids = [aws_security_group.concierge_sg.id]

  root_block_device {
    volume_size = 10
    volume_type = "gp3"
  }

  user_data = <<-EOF
    #!/bin/bash
    apt-get update
    apt-get install -y python3-pip python3-venv nginx certbot python3-certbot-nginx

    # Create app and data directories
    mkdir -p /opt/concierge/app /opt/concierge/data
    chown -R ubuntu:ubuntu /opt/concierge

    echo "Concierge server ready for deployment" > /opt/concierge/status.txt
  EOF

  tags = {
    Name    = "concierge-api-server"
    Project = "concierge-aws-monce-ai"
  }
}

# Route53 DNS Record
resource "aws_route53_record" "concierge_dns" {
  zone_id = "Z08902341SIIJX80NFN4N" # aws.monce.ai hosted zone
  name    = "concierge.aws.monce.ai"
  type    = "A"
  ttl     = 60
  records = [aws_instance.concierge_server.public_ip]
}

# Outputs
output "instance_id" {
  value = aws_instance.concierge_server.id
}

output "public_ip" {
  value = aws_instance.concierge_server.public_ip
}

output "ssh_command" {
  value = "ssh -i ~/.ssh/${var.key_name}.pem ubuntu@${aws_instance.concierge_server.public_ip}"
}

output "url" {
  value = "https://concierge.aws.monce.ai"
}
