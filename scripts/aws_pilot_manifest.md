# AWS pilot resources (created 2026-08-12, eu-central-1)

Everything tagged/prefixed `sunline-pilot`. Remove with
`scripts/aws_pilot_teardown.sh` (add `--bucket-too` for zero trace).

| resource | id |
|---|---|
| S3 bucket (STAYS after teardown) | sunline-pilot-774672614717 |
| IAM role | sunline-pilot-ec2 (inline: s3-pilot-bucket; managed: AmazonSSMManagedInstanceCore) |
| instance profile | sunline-pilot-profile |
| security group | sg-0f38093cf9c1ab483 (no ingress, default VPC) |
| EC2 | spot m7i.48xlarge, tag Name=sunline-pilot, self-terminating, EBS DeleteOnTermination |
