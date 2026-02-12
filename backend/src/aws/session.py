import boto3
from botocore.exceptions import BotoCoreError, ProfileNotFound
from functools import lru_cache

from .config import settings

@lru_cache(maxsize=1)
def get_aws_session():
    """
    Return a cached boto3 Session configured from application settings (AWS profile and region).
    """
    profile = settings.AWS_PROFILE
    region = settings.AWS_REGION
    
    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        return session
    
    except ProfileNotFound as e:
        raise RuntimeError(
            f"AWS profile {profile} was not found"
        ) from e
    
    except BotoCoreError as e:
        raise RuntimeError(
            f"failed to create AWS session (profile={profile}, region={region})"
        ) from e
    