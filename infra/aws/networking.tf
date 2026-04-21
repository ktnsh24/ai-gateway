# =============================================================================
# VPC & Security Groups
# =============================================================================
# Uses default VPC for dev. In production, create a dedicated VPC.
# =============================================================================

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "gateway" {
  name        = "${local.prefix}-sg"
  description = "AI Gateway security group"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 8100
    to_port     = 8100
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Gateway API"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }
}
