#!/usr/bin/env python3
"""
Shared R2 Cloudflare Storage Upload Module

Provides functionality to upload files to R2 (S3-compatible) storage
and generate public URLs for use in import scripts.

Environment Variables Required:
- IMPORT_R2_ENDPOINT_URL: Cloudflare R2 endpoint URL (https://<accountid>.r2.cloudflarestorage.com)
- IMPORT_R2_ACCESS_KEY_ID: R2 access key ID
- IMPORT_R2_SECRET_ACCESS_KEY: R2 secret access key
- IMPORT_R2_REGION: R2 region (e.g., auto, wnam, enam, weur, eeur, apac)
- IMPORT_R2_BUCKET_NAME: Name of the R2 bucket
- IMPORT_R2_PUBLIC_URL_BASE: Base URL for public access (optional, defaults to bucket URL)
"""

import os
import boto3
import requests
import io
from urllib.parse import urlparse
import hashlib
import mimetypes
from botocore.exceptions import ClientError, NoCredentialsError


class R2UploaderError(Exception):
    """Custom exception for R2 uploader errors"""
    pass


class R2Uploader:
    """Upload files to Cloudflare R2 storage"""

    def __init__(self):
        """Initialize R2 client with environment variables"""
        self.endpoint_url = os.getenv("IMPORT_R2_ENDPOINT_URL")
        self.access_key_id = os.getenv("IMPORT_R2_ACCESS_KEY_ID")
        self.secret_access_key = os.getenv("IMPORT_R2_SECRET_ACCESS_KEY")
        self.region = os.getenv("IMPORT_R2_REGION", "auto")
        self.bucket_name = os.getenv("IMPORT_R2_BUCKET_NAME")
        self.public_url_base = os.getenv("IMPORT_R2_PUBLIC_URL_BASE")

        # Validate required environment variables
        self._validate_config()

        # Initialize S3 client for R2
        self.s3_client = boto3.client(
            service_name="s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.region,
        )

        # Set default public URL base if not provided
        if not self.public_url_base:
            # Extract account ID from endpoint URL
            # https://<accountid>.r2.cloudflarestorage.com -> https://<bucket>.<accountid>.r2.cloudflarestorage.com
            if self.endpoint_url and self.bucket_name:
                account_part = self.endpoint_url.replace("https://", "").replace(".r2.cloudflarestorage.com", "")
                self.public_url_base = f"https://{self.bucket_name}.{account_part}.r2.cloudflarestorage.com"

    def _validate_config(self):
        """Validate that all required environment variables are set"""
        required_vars = [
            ("IMPORT_R2_ENDPOINT_URL", self.endpoint_url),
            ("IMPORT_R2_ACCESS_KEY_ID", self.access_key_id),
            ("IMPORT_R2_SECRET_ACCESS_KEY", self.secret_access_key),
            ("IMPORT_R2_BUCKET_NAME", self.bucket_name),
        ]

        missing_vars = [var_name for var_name, var_value in required_vars if not var_value]

        if missing_vars:
            raise R2UploaderError(
                f"Missing required environment variables: {', '.join(missing_vars)}\n"
                f"Please set all IMPORT_R2_* environment variables before using the R2 uploader."
            )

    def file_exists(self, key):
        """Check if a file already exists in the bucket"""
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            else:
                raise R2UploaderError(f"Error checking file existence: {e}")

    def upload_url(self, source_url, overwrite=False, timeout=30):
        """
        Download a file from URL and upload to R2 bucket

        Args:
            source_url (str): URL to download the file from
            key (str): S3 key (path) where to store the file in the bucket
            overwrite (bool): Whether to overwrite existing files
            timeout (int): Timeout for downloading the source file

        Returns:
            str: Public URL of the uploaded file

        Raises:
            R2UploaderError: If upload fails
        """
        key = self.generate_key_from_url(source_url)

        # Check if file already exists
        if not overwrite and self.file_exists(key):
            print(f"  File already exists in R2: {key}")
            return self.get_public_url(key)

        try:
            # Download the file from the source URL
            print(f"  Downloading from: {source_url}")
            response = requests.get(source_url, timeout=timeout, stream=True)
            response.raise_for_status()

            # Get file content
            file_content = response.content

            # Determine content type
            content_type = response.headers.get('content-type')
            if not content_type:
                # Guess content type from URL
                content_type, _ = mimetypes.guess_type(source_url)
                if not content_type:
                    content_type = 'application/octet-stream'

            # Upload to R2
            print(f"  Uploading to R2: {key}")
            self.s3_client.upload_fileobj(
                io.BytesIO(file_content),
                self.bucket_name,
                key,
                ExtraArgs={
                    'ContentType': content_type,
                    'CacheControl': 'public, max-age=31536000'  # Cache for 1 year
                }
            )

            public_url = self.get_public_url(key)
            print(f"  ✓ Uploaded to R2: {public_url}")
            return public_url

        except requests.RequestException as e:
            raise R2UploaderError(f"Failed to download from {source_url}: {e}")
        except ClientError as e:
            raise R2UploaderError(f"Failed to upload to R2: {e}")
        except Exception as e:
            raise R2UploaderError(f"Unexpected error during upload: {e}")

    def upload_file_content(self, file_content, key, content_type=None, overwrite=False):
        """
        Upload file content directly to R2 bucket

        Args:
            file_content (bytes): Raw file content to upload
            key (str): S3 key (path) where to store the file in the bucket
            content_type (str): MIME type of the file (optional)
            overwrite (bool): Whether to overwrite existing files

        Returns:
            str: Public URL of the uploaded file

        Raises:
            R2UploaderError: If upload fails
        """
        # Check if file already exists
        if not overwrite and self.file_exists(key):
            print(f"  File already exists in R2: {key}")
            return self.get_public_url(key)

        try:
            # Set default content type
            if not content_type:
                content_type, _ = mimetypes.guess_type(key)
                if not content_type:
                    content_type = 'application/octet-stream'

            # Upload to R2
            print(f"  Uploading to R2: {key}")
            self.s3_client.upload_fileobj(
                io.BytesIO(file_content),
                self.bucket_name,
                key,
                ExtraArgs={
                    'ContentType': content_type,
                    'CacheControl': 'public, max-age=31536000'  # Cache for 1 year
                }
            )

            public_url = self.get_public_url(key)
            print(f"  ✓ Uploaded to R2: {public_url}")
            return public_url

        except ClientError as e:
            raise R2UploaderError(f"Failed to upload to R2: {e}")
        except Exception as e:
            raise R2UploaderError(f"Unexpected error during upload: {e}")

    def delete_file(self, key):
        """
        Delete a file from the R2 bucket

        Args:
            key (str): S3 key of the file to delete

        Returns:
            bool: True if deletion was successful

        Raises:
            R2UploaderError: If deletion fails
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
            print(f"  ✓ Deleted from R2: {key}")
            return True
        except ClientError as e:
            raise R2UploaderError(f"Failed to delete from R2: {e}")

    def get_public_url(self, key):
        """
        Get the public URL for a file in the bucket

        Args:
            key (str): S3 key of the file

        Returns:
            str: Public URL of the file
        """
        if self.public_url_base:
            return f"{self.public_url_base}/{key}"
        else:
            # Fallback to constructing URL from endpoint
            return f"{self.endpoint_url}/{self.bucket_name}/{key}"

    def generate_key_from_url(self, source_url) -> str:
        """
        Generate a unique key for storing a file based on its source URL

        Args:
            source_url (str): Original URL of the file
            prefix (str): Prefix for the key (folder structure)

        Returns:
            str: Generated key for the file
        """
        return str(hashlib.md5(source_url.encode()).hexdigest()[:20])

if __name__ == "__main__":
    # Test the R2 connection when run directly
    test_r2_connection()
