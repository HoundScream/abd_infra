variable "tf_yc_cloud_id" {
  description = "Yandex.Cloud cloud id"
  type        = string
  default     = ""
}

variable "tf_yc_folder_id" {
  description = "Yandex.Cloud folder id"
  type        = string
  default     = ""
}

variable "tf_yc_token" {
  description = "Yandex.Cloud iam token"
  type        = string
  default     = ""
}

variable "compute_vm_name" {
  description = "Compute vm name"
  type        = string
  default     = ""
}

variable "compute_platform_id" {
  description = "Compute platform ID"
  type        = string
  default     = ""
}

variable "compute_cpu_cores" {
  description = "CPU cores num"
  type        = number
  default     = 1
}

variable "compute_mem_gb" {
  description = "Ram gigabytes"
  type        = number
  default     = 1
}

variable "compute_cpu_core_fraction" {
  description = "CPU subscription ratio"
  type        = number
  default     = 1
}

variable "compute_image_id" {
  description = "OS image id"
  type        = string
  default     = ""
}

variable "compute_volume_size" {
  description = "Compute volume size in gigabytes"
  type        = number
  default     = 20
}

variable "vpc_subnet_id" {
  description = "VPS subnet id"
  type        = string
  default     = ""
}

variable "vpc_ip_address" {
  description = "VPC IP address"
  type        = string
  default     = ""
}

variable "vpc_nat_enable" {
  description = "VPS port NAT enabled"
  type        = bool
  default     = false
}

variable "vpc_nat_ip_address" {
  description = "VPS use this external ip address for nat"
  type        = string
  default     = ""
}

variable "compute_ssh_keys" {
  description = "Public SSH keys for new VMs"
  type        = string
  default     = ""
}
