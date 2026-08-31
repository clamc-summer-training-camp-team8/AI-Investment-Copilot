output "ecs_id" {
  description = "集成 ECS ID。"
  value       = huaweicloud_compute_instance.integration.id
}

output "ecs_private_ip" {
  description = "集成 ECS 私网地址。"
  value       = huaweicloud_compute_instance.integration.network[0].fixed_ip_v4
}

output "eip_address" {
  description = "需要绑定到集成域名 A 记录的公网地址。"
  value       = huaweicloud_vpc_eip.integration.address
}

output "ssh_command" {
  description = "首次配置服务器时使用。"
  value       = "ssh ${var.deploy_user}@${huaweicloud_vpc_eip.integration.address}"
}

output "deployment_directory" {
  value = "/opt/ai-investment-copilot/deploy"
}
