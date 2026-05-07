# ============================================================
# Root module — wires all child modules together
# ============================================================
#
# Note on the log group name: the CloudWatch log group name is
# computed deterministically here so it can be passed to both the
# monitoring module (which creates the resource) and the ECS module
# (which references it in the task definition log driver config)
# without creating a circular dependency.
locals {
  log_group_name = "/ecs/${var.project}"
}

module "networking" {
  source = "./modules/networking"

  project            = var.project
  environment        = var.environment
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
  container_port     = var.container_port
}

module "iam" {
  source = "./modules/iam"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region
  account_id  = local.account_id
}

module "ecr" {
  source = "./modules/ecr"

  project     = var.project
  environment = var.environment
}

module "secrets" {
  source = "./modules/secrets"

  project        = var.project
  environment    = var.environment
  mesh_api_key   = var.mesh_api_key
  qdrant_url     = var.qdrant_url
  qdrant_api_key = var.qdrant_api_key
  cohere_api_key = var.cohere_api_key
  tavily_api_key = var.tavily_api_key
  jina_api_key   = var.jina_api_key
}

module "alb" {
  source = "./modules/alb"

  project        = var.project
  environment    = var.environment
  vpc_id         = module.networking.vpc_id
  public_subnets = module.networking.public_subnet_ids
  alb_sg_id      = module.networking.alb_sg_id
  container_port = var.container_port
}

module "ecs" {
  source = "./modules/ecs"

  project              = var.project
  environment          = var.environment
  aws_region           = var.aws_region
  ecr_image_url        = local.ecr_image_url
  container_port       = var.container_port
  cpu                  = var.cpu
  memory               = var.memory
  desired_count        = var.desired_count
  min_capacity         = var.min_capacity
  max_capacity         = var.max_capacity
  execution_role_arn   = module.iam.execution_role_arn
  task_role_arn        = module.iam.task_role_arn
  private_subnet_ids   = module.networking.private_subnet_ids
  ecs_sg_id            = module.networking.ecs_sg_id
  target_group_arn     = module.alb.target_group_arn
  log_group_name       = local.log_group_name
  secret_arns          = module.secrets.secret_arns
}

module "monitoring" {
  source = "./modules/monitoring"

  project            = var.project
  environment        = var.environment
  aws_region         = var.aws_region
  log_retention_days = var.log_retention_days
  alarm_email        = var.alarm_email
  log_group_name     = local.log_group_name
  ecs_cluster_name   = module.ecs.cluster_name
  ecs_service_name   = module.ecs.service_name
  alb_arn_suffix     = module.alb.alb_arn_suffix
  tg_arn_suffix      = module.alb.tg_arn_suffix
}
