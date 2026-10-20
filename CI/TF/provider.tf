terraform {
  required_version = ">= 0.13"
  required_providers {
    yandex = {
      source = "yandex-cloud/yandex"
    }
  }
}

provider "yandex" {
  zone = "ru-central1-a"
  cloud_id  = var.tf_yc_cloud_id
  folder_id = var.tf_yc_folder_id
}