locals {
  inbound_web_rules = {
    for item in flatten([
      for cidr in var.web_source_cidrs : [
        { key = "${replace(cidr, "/", "-")}-80", cidr = cidr, port = 80 },
        { key = "${replace(cidr, "/", "-")}-443", cidr = cidr, port = 443 }
      ]
    ]) : item.key => item
  }
}

resource "huaweicloud_vpc" "integration" {
  name = "${var.project_name}-vpc"
  cidr = var.vpc_cidr
  tags = var.common_tags
}

resource "huaweicloud_vpc_subnet" "integration" {
  name              = "${var.project_name}-subnet"
  cidr              = var.subnet_cidr
  gateway_ip        = var.subnet_gateway_ip
  vpc_id            = huaweicloud_vpc.integration.id
  availability_zone = var.availability_zone
  tags              = var.common_tags
}

resource "huaweicloud_networking_secgroup" "integration" {
  name                 = "${var.project_name}-sg"
  description          = "AI Investment Copilot integration gateway only"
  delete_default_rules = true
  tags                 = var.common_tags
}

resource "huaweicloud_networking_secgroup_rule" "egress_ipv4" {
  security_group_id = huaweicloud_networking_secgroup.integration.id
  direction         = "egress"
  ethertype         = "IPv4"
  remote_ip_prefix  = "0.0.0.0/0"
  description       = "Required for image pulls, ACME and approved model gateways"
}

resource "huaweicloud_networking_secgroup_rule" "ssh" {
  for_each = var.ssh_source_cidrs

  security_group_id = huaweicloud_networking_secgroup.integration.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = each.value
  description       = "SSH from an approved office or VPN egress"
}

resource "huaweicloud_networking_secgroup_rule" "web" {
  for_each = local.inbound_web_rules

  security_group_id = huaweicloud_networking_secgroup.integration.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = each.value.port
  port_range_max    = each.value.port
  remote_ip_prefix  = each.value.cidr
  description       = "HTTPS gateway and ACME validation"
}

resource "huaweicloud_compute_instance" "integration" {
  name               = "${var.project_name}-ecs"
  image_id           = var.ecs_image_id
  flavor_id          = var.ecs_flavor_id
  key_pair           = var.ecs_key_pair
  security_group_ids = [huaweicloud_networking_secgroup.integration.id]
  availability_zone  = var.availability_zone

  system_disk_type = var.ecs_system_disk_type
  system_disk_size = var.ecs_system_disk_size_gb

  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    deploy_user = var.deploy_user
  })

  network {
    uuid = huaweicloud_vpc_subnet.integration.id
  }

  tags = var.common_tags
}

resource "huaweicloud_vpc_eip" "integration" {
  name = "${var.project_name}-eip"

  publicip {
    type = "5_bgp"
  }

  bandwidth {
    name        = "${var.project_name}-bandwidth"
    size        = var.eip_bandwidth_mbit
    share_type  = "PER"
    charge_mode = "traffic"
  }

  tags = var.common_tags
}

resource "huaweicloud_compute_eip_associate" "integration" {
  public_ip   = huaweicloud_vpc_eip.integration.address
  instance_id = huaweicloud_compute_instance.integration.id
}

