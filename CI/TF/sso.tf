resource "yandex_compute_instance" "sso" {
  description           = "Default SSO server"
  name                  = "sso"
  hostname              = var.compute_vm_name
  platform_id           = var.compute_platform_id
  allow_stopping_for_update = true

  resources {
    cores               = var.compute_cpu_cores
    memory              = var.compute_mem_gb
  }

  boot_disk {
    initialize_params {
      image_id          = var.compute_image_id
      size              = var.compute_volume_size
    }
  }

  network_interface {
    ip_address          = var.vpc_ip_address
    subnet_id           = var.vpc_subnet_id
    nat                 = var.vpc_nat_enable
    nat_ip_address      = var.vpc_nat_ip_address
    security_group_ids = [yandex_vpc_security_group.default_local_network_sg.id, yandex_vpc_security_group.sso_server_sg.id]
  }

  metadata = {
    ssh-keys            = var.compute_ssh_keys
    serial-port-enable  = 1
  }

}
