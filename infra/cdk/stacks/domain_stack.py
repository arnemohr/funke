"""Domain stack for Funke Event Management System.

Configures:
- ACM certificate for custom domain (DNS validation)
"""

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_certificatemanager as acm
from constructs import Construct


class DomainStack(Stack):
    """ACM certificate stack for custom domain."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str,
        domain_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.domain_name = domain_name

        # ACM Certificate for the custom domain
        # Note: Certificate MUST be in us-east-1 for CloudFront
        # This stack should be deployed to us-east-1
        self.certificate = acm.Certificate(
            self,
            "Certificate",
            domain_name=domain_name,
            validation=acm.CertificateValidation.from_dns(),
            certificate_name=f"funke-{env_name}-certificate",
        )

        # Output the certificate ARN for use by other stacks
        CfnOutput(
            self,
            "CertificateArn",
            value=self.certificate.certificate_arn,
            description="ACM certificate ARN for CloudFront",
            export_name=f"funke-{env_name}-certificate-arn",
        )

        # Output DNS validation instructions
        CfnOutput(
            self,
            "DomainName",
            value=domain_name,
            description="Domain name for the application",
            export_name=f"funke-{env_name}-domain-name",
        )
