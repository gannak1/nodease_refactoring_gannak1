terraform {
  required_version = ">= 1.5.0"
}

variable "environment" {
  type    = string
  default = "ci"

  validation {
    condition     = length(trimspace(var.environment)) > 0
    error_message = "environment must not be empty"
  }
}

output "environment" {
  value = var.environment
}
