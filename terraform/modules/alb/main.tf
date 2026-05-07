locals {
  name_prefix = "${var.project}-${var.environment}"
}

# ── Application Load Balancer ─────────────────────────────────────────────────

resource "aws_lb" "main" {
  name               = "${var.project}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.alb_sg_id]
  subnets            = var.public_subnets

  # Enable deletion protection in production to prevent accidental removal
  enable_deletion_protection = true

  # Access logging — disabled by default to avoid requiring an S3 bucket;
  # enable by adding an access_logs block with a bucket name.

  tags = {
    Name = "${var.project}-alb"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# ── Target Group ──────────────────────────────────────────────────────────────

resource "aws_lb_target_group" "main" {
  name        = "${var.project}-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip" # Required for Fargate awsvpc networking

  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 30

  tags = {
    Name = "${var.project}-tg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ── HTTP Listener (port 80) ───────────────────────────────────────────────────

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.main.arn
  }

  tags = {
    Name = "${var.project}-http-listener"
  }
}
