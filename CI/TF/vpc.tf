data "yandex_vpc_network" "default" {
  folder_id = var.tf_yc_folder_id
  name      = "default"
}

resource "yandex_vpc_subnet" "default-ru-central1-a" {
  folder_id      = var.tf_yc_folder_id
  name           = "default-ru-central1-a"
  v4_cidr_blocks = ["10.128.0.0/24"]
  zone           = "ru-central1-a"
  network_id     = data.yandex_vpc_network.default.id
  route_table_id = yandex_vpc_route_table.default_route_table.id
}

resource "yandex_vpc_gateway" "default_nat_gateway" {
  name = "default-nat-gateway"
  shared_egress_gateway {}
}

resource "yandex_vpc_route_table" "default_route_table" {
  name       = "default-route-table"
  network_id = data.yandex_vpc_network.default.id

  static_route {
    destination_prefix = "0.0.0.0/0"
    gateway_id         = yandex_vpc_gateway.default_nat_gateway.id
  }

  static_route {
    destination_prefix = "10.255.255.0/25"
    next_hop_address = "10.128.0.5"
  }

  static_route {
    destination_prefix = "10.255.255.128/25"
    next_hop_address = "10.128.0.5"
  }
}

resource "yandex_vpc_security_group" "vpn_server_sg" {
  network_id = data.yandex_vpc_network.default.id
  name = "vpn_server_sg"

  ingress {
    description = "Allow SSH from any"
    protocol = "TCP"
    port = 22
    v4_cidr_blocks = ["0.0.0/0"]
  }

  ingress {
    description = "Allow certbot temp server from any"
    protocol = "TCP"
    port = 80
    v4_cidr_blocks = ["0.0.0/0"]
  }

  ingress {
    description = "Allow openconnect vpn server connections from any"
    protocol = "ANY"
    port = 443
    v4_cidr_blocks = ["0.0.0/0"]
  }

  egress {
    description = "Allow egress to any"
    protocol = "ANY"
    v4_cidr_blocks = ["0.0.0/0"]
  }
}

resource "yandex_vpc_security_group" "sso_server_sg" {
  network_id = data.yandex_vpc_network.default.id
  name = "sso_server_sg"

  ingress {
    description = "Allow SSO from any"
    protocol = "TCP"
    port = 8443
    v4_cidr_blocks = ["0.0.0/0"]
  }

  egress {
    description = "Allow egress to any"
    protocol = "ANY"
    v4_cidr_blocks = ["0.0.0/0"]
  }
}

resource "yandex_vpc_security_group" "default_local_network_sg" {
  network_id = data.yandex_vpc_network.default.id
  name = "default_local_network_sg"

  ingress {
    description = "Allow all from local and infra networks"
    protocol = "ANY"
    v4_cidr_blocks = ["10.128.0.0/24", "10.255.255.0/25"]
  }

  egress {
    description = "Allow all to local and infra networks"
    protocol = "ANY"
    v4_cidr_blocks = ["10.128.0.0/24", "10.255.255.0/25", "10.255.255.128/25", "213.180.204.183/32", "158.160.127.119/32", "91.189.91.0/25", "185.125.190.0/25"]
  }
}

resource "yandex_vpc_security_group" "armds_users_sg" {
  network_id = data.yandex_vpc_network.default.id
  name = "armds_users_sg"

  ingress {
    description = "Allow RDP from ARMDS users"
    protocol = "TCP"
    port = 3389
    v4_cidr_blocks = ["10.128.0.0/24", "10.255.255.128/25", "10.255.255.0/25"]
  }

  egress {
    description = "Allow whitelist networks"
    protocol = "ANY"
    v4_cidr_blocks = ["178.154.131.208/29", "213.180.193.243/32", "87.250.250.0/24", "213.180.204.0/24", "130.193.32.0/19", "130.193.61.0/24", "130.193.62.0/24", "178.154.192.0/19", "178.154.224.0/19", "178.154.243.0/24", "178.154.244.0/24", "178.154.245.0/24", "185.206.164.0/22", "193.32.216.0/22", "193.32.216.0/24", "193.32.217.0/24", "217.28.224.0/20", "51.250.0.0/17", "62.84.112.0/20", "84.201.128.0/18", "84.201.184.0/22", "84.201.188.0/23", "84.252.128.0/20"]
  }
}