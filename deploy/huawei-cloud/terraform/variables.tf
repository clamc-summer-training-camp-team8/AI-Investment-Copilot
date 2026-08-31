variable "region" {
  description = "华为云区域，例如 cn-south-1。凭据从 HW_ACCESS_KEY/HW_SECRET_KEY 读取。"
  type        = string
}

variable "availability_zone" {
  description = "ECS 和子网所在可用区，例如 cn-south-1a。"
  type        = string
}

variable "project_name" {
  description = "资源名称前缀。"
  type        = string
  default     = "ai-investment-copilot-integration"

  validation {
    condition     = can(regex("^[a-zA-Z0-9_-]{1,48}$", var.project_name))
    error_message = "project_name 仅允许字母、数字、下划线和连字符，且不超过 48 个字符。"
  }
}

variable "vpc_cidr" {
  description = "集成环境 VPC CIDR。"
  type        = string
  default     = "10.80.0.0/16"
}

variable "subnet_cidr" {
  description = "ECS 子网 CIDR。"
  type        = string
  default     = "10.80.10.0/24"
}

variable "subnet_gateway_ip" {
  description = "ECS 子网网关。"
  type        = string
  default     = "10.80.10.1"
}

variable "ecs_flavor_id" {
  description = "区域内可用的 ECS 规格；建议集成环境至少 4 vCPU / 16 GiB。"
  type        = string
}

variable "ecs_image_id" {
  description = "Ubuntu 24.04 LTS 64-bit 公共镜像 ID。"
  type        = string
}

variable "ecs_key_pair" {
  description = "已存在的 ECS SSH 密钥对名称。"
  type        = string
}

variable "ecs_system_disk_type" {
  description = "系统盘类型，按区域选择 SSD/SAS/GPSSD 等。"
  type        = string
  default     = "SSD"
}

variable "ecs_system_disk_size_gb" {
  description = "系统盘容量；同时承载容器持久卷，建议至少 200 GiB。"
  type        = number
  default     = 200

  validation {
    condition     = var.ecs_system_disk_size_gb >= 100
    error_message = "集成环境系统盘不得小于 100 GiB。"
  }
}

variable "ssh_source_cidrs" {
  description = "允许 SSH 的办公网/VPN 出口 CIDR；禁止使用 0.0.0.0/0。"
  type        = set(string)

  validation {
    condition     = length(var.ssh_source_cidrs) > 0 && !contains(var.ssh_source_cidrs, "0.0.0.0/0")
    error_message = "至少提供一个 SSH 来源 CIDR，且不得为 0.0.0.0/0。"
  }
}

variable "web_source_cidrs" {
  description = "允许访问 80/443 的 CIDR。Caddy 自动签证书时需包含公网；应用仍由独立账号保护。"
  type        = set(string)
  default     = ["0.0.0.0/0"]
}

variable "eip_bandwidth_mbit" {
  description = "按流量计费的独享 EIP 带宽上限。"
  type        = number
  default     = 10

  validation {
    condition     = var.eip_bandwidth_mbit >= 1 && var.eip_bandwidth_mbit <= 300
    error_message = "EIP 带宽必须在 1 到 300 Mbit/s 之间。"
  }
}

variable "deploy_user" {
  description = "Ubuntu 镜像中的运维用户。"
  type        = string
  default     = "ubuntu"
}

variable "common_tags" {
  description = "资源治理标签。"
  type        = map(string)
  default = {
    environment = "integration"
    product     = "ai-investment-copilot"
    managed-by  = "terraform"
  }
}

