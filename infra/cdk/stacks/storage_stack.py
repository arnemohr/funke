"""Storage stack for Funke Event Management System.

Configures:
- S3 bucket for frontend static assets
- CloudFront distribution for CDN
- Custom domain with SSL certificate
- API Gateway routing via /api/* path
"""

from typing import TYPE_CHECKING

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from constructs import Construct

if TYPE_CHECKING:
    from .api_stack import ApiStack
    from .domain_stack import DomainStack


class StorageStack(Stack):
    """S3 + CloudFront stack for frontend hosting."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str,
        domain_stack: "DomainStack | None" = None,
        api_stack: "ApiStack | None" = None,
        domain_name: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        removal_policy = (
            RemovalPolicy.DESTROY if env_name == "dev" else RemovalPolicy.RETAIN
        )

        # S3 bucket for frontend assets
        self.frontend_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            bucket_name=f"funke-{env_name}-frontend",
            removal_policy=removal_policy,
            auto_delete_objects=env_name == "dev",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
        )

        # S3 origin for frontend
        s3_origin = origins.S3BucketOrigin.with_origin_access_control(
            self.frontend_bucket,
        )

        # CloudFront Function for SPA routing:
        # Rewrites paths without file extensions to /index.html so Vue Router works.
        # This replaces error_responses which applied globally (breaking API 403/404).
        spa_rewrite_function = cloudfront.Function(
            self,
            "SpaRewriteFunction",
            function_name=f"funke-{env_name}-spa-rewrite",
            code=cloudfront.FunctionCode.from_inline(
                "function handler(event) {\n"
                "  var request = event.request;\n"
                "  var uri = request.uri;\n"
                "  // If the URI has a file extension, serve as-is (JS, CSS, images, etc.)\n"
                "  if (uri.includes('.')) {\n"
                "    return request;\n"
                "  }\n"
                "  // Otherwise rewrite to /index.html for SPA client-side routing\n"
                "  request.uri = '/index.html';\n"
                "  return request;\n"
                "}"
            ),
        )

        # Build additional behaviors for API routing
        additional_behaviors: dict[str, cloudfront.BehaviorOptions] = {}

        if api_stack is not None:
            # API Gateway origin
            api_origin = origins.HttpOrigin(
                f"{api_stack.http_api.http_api_id}.execute-api.{self.region}.amazonaws.com",
                origin_path="",
                protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
            )

            # API behavior for /api/* path
            # Use managed CACHING_DISABLED policy and forward Authorization via origin request
            additional_behaviors["/api/*"] = cloudfront.BehaviorOptions(
                origin=api_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD_OPTIONS,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            )

        # Configure domain aliases and certificate
        domain_names: list[str] | None = None
        certificate: acm.ICertificate | None = None

        if domain_stack is not None and domain_name is not None:
            domain_names = [domain_name]
            certificate = domain_stack.certificate

        # CloudFront distribution with S3 Origin Access Control (OAC)
        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=s3_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=spa_rewrite_function,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    ),
                ],
            ),
            additional_behaviors=additional_behaviors if additional_behaviors else None,
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            domain_names=domain_names,
            certificate=certificate,
        )

        # Outputs for frontend deployment
        CfnOutput(
            self,
            "FrontendBucketName",
            value=self.frontend_bucket.bucket_name,
            description="S3 bucket name for frontend assets",
            export_name=f"funke-{env_name}-frontend-bucket",
        )

        CfnOutput(
            self,
            "DistributionId",
            value=self.distribution.distribution_id,
            description="CloudFront distribution ID",
            export_name=f"funke-{env_name}-distribution-id",
        )

        CfnOutput(
            self,
            "DistributionDomainName",
            value=self.distribution.distribution_domain_name,
            description="CloudFront distribution domain name",
            export_name=f"funke-{env_name}-distribution-domain",
        )

        if domain_name:
            CfnOutput(
                self,
                "CustomDomainName",
                value=domain_name,
                description="Custom domain name for the application",
                export_name=f"funke-{env_name}-custom-domain",
            )
