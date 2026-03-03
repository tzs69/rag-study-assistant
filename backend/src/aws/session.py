import boto3
from botocore.exceptions import BotoCoreError, ProfileNotFound
from functools import lru_cache
import os

from .config import settings

@lru_cache(maxsize=1)
def get_aws_session():
    """
    Return a cached boto3 Session configured for local dev or Lambda runtime.
    """
    # Lambda must always use the execution role, never local profile config
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        profile = None
    else:
        profile = (settings.AWS_SSO_PROFILE or "").strip() or None
    region = settings.aws_region_resolved

    try:
        # In Lambda, omit profile_name so boto3 uses the execution role credentials
        if profile:
            session = boto3.Session(profile_name=profile, region_name=region)
        else:
            session = boto3.Session(region_name=region)
        return session

    except ProfileNotFound as e:
        raise RuntimeError(
            f"AWS profile {profile} was not found"
        ) from e

    except BotoCoreError as e:
        raise RuntimeError(
            f"failed to create AWS session (profile={profile}, region={region})"
        ) from e
    
