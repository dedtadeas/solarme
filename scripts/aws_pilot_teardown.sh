#!/bin/bash
# Tear down EVERYTHING the SunLine EC2 pilot created, in dependency order.
# Written BEFORE the resources themselves, so cleanup never depends on memory.
#
# After this script, the AWS account differs from its pre-pilot state by
# exactly one thing: the S3 bucket (kept deliberately — results live there).
# Pass --bucket-too to remove even that and leave zero trace.
#
# Idempotent: every step tolerates "already gone".

set -uo pipefail
REGION=eu-central-1
ROLE=sunline-pilot-ec2
PROFILE=sunline-pilot-profile
SG=sunline-pilot-nossh
BUCKET="sunline-pilot-$(aws sts get-caller-identity --query Account --output text)"

echo "== instances tagged sunline-pilot =="
IDS=$(aws ec2 describe-instances --region $REGION \
  --filters "Name=tag:Name,Values=sunline-pilot" \
            "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[].Instances[].InstanceId' --output text)
if [ -n "$IDS" ]; then
  echo "terminating: $IDS"
  aws ec2 terminate-instances --region $REGION --instance-ids $IDS >/dev/null
  aws ec2 wait instance-terminated --region $REGION --instance-ids $IDS
fi

echo "== instance profile =="
aws iam remove-role-from-instance-profile \
  --instance-profile-name $PROFILE --role-name $ROLE 2>/dev/null || true
aws iam delete-instance-profile --instance-profile-name $PROFILE 2>/dev/null || true

echo "== role =="
aws iam detach-role-policy --role-name $ROLE \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore 2>/dev/null || true
aws iam delete-role-policy --role-name $ROLE --policy-name s3-pilot-bucket 2>/dev/null || true
aws iam delete-role --role-name $ROLE 2>/dev/null || true

echo "== security group =="
SGID=$(aws ec2 describe-security-groups --region $REGION \
  --filters "Name=group-name,Values=$SG" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)
if [ "$SGID" != "None" ] && [ -n "$SGID" ]; then
  # ENIs linger briefly after termination; retry a few times.
  for i in 1 2 3 4 5 6; do
    aws ec2 delete-security-group --region $REGION --group-id "$SGID" 2>/dev/null && break
    echo "  SG busy, retry $i/6 in 20s"; sleep 20
  done
fi

if [ "${1:-}" = "--bucket-too" ]; then
  echo "== bucket (requested) =="
  aws s3 rb "s3://$BUCKET" --force
else
  echo "== bucket kept: s3://$BUCKET (pass --bucket-too to remove) =="
fi

echo "== verify =="
aws iam get-role --role-name $ROLE 2>/dev/null && echo "ROLE STILL EXISTS" || echo "role gone"
aws iam get-instance-profile --instance-profile-name $PROFILE 2>/dev/null >/dev/null && echo "PROFILE STILL EXISTS" || echo "profile gone"
echo "teardown complete"
