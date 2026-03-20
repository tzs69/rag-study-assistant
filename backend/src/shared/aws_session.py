import boto3
from botocore.exceptions import BotoCoreError, ProfileNotFound
from functools import lru_cache
import os
from .config import settings

@lru_cache(maxsize=1)
def get_aws_session():
    """
    Return a cached boto3 Session configured for local dev or Lambda runtime.
    If running locally with a sso/default profile, set profile region to us-east-1 for model availability
    """
    try:
        if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
            profile = None
        else:
            profile = (settings.AWS_SSO_PROFILE or "").strip() or None

        if profile:
            # Make sure region = 'us-east-1' for current active aws profile in ~/.aws/config
            region = settings.AWS_SSO_REGION
            session = boto3.Session(profile_name=profile, region_name=region)
        else:
            region = os.getenv("AWS_REGION")
            session = boto3.Session(region_name=region)
        return session
    
    except ProfileNotFound as e:
        raise RuntimeError(
            f"AWS profile {profile} was not found"
        ) from e

    except BotoCoreError as e:
        raise RuntimeError(
            f"failed to create AWS session (profile={profile})"
        ) from e
