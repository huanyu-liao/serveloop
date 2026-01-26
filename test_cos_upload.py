import os
import sys
import time
import urllib.request
import urllib.error

# Ensure we can import from the saas package
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set environment variables as requested
os.environ["COS_BUCKET"] = "7072-prod-8g1mxp1pb9d47595-1385357501"
os.environ["COS_REGION"] = "ap-shanghai"
os.environ["STORAGE_DRIVER"] = "COS"
os.environ["WX_CLOUD_ENV_ID"] = "prod-8g1mxp1pb9d47595"

# NOTE: Since this is a local script, you likely need to provide COS secrets 
# unless you are somehow tunneling to the cloud env or have them set globally.
# Uncomment and fill these if needed, or ensure they are in your shell env.
# os.environ["COS_SECRET_ID"] = "YOUR_SECRET_ID"
# os.environ["COS_SECRET_KEY"] = "YOUR_SECRET_KEY"

def create_dummy_image():
    # Create a simple 1x1 GIF byte sequence
    return b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'

def run_test():
    print(">>> Setting up environment...")
    print(f"COS_BUCKET: {os.environ.get('COS_BUCKET')}")
    print(f"COS_REGION: {os.environ.get('COS_REGION')}")
    
    try:
        from saas.services.storage_service import upload_file_stream
    except ImportError as e:
        print(f"Error importing storage_service: {e}")
        print("Make sure you have installed requirements (especially cos-python-sdk-v5)")
        return

    # Check for secrets
    if not (os.getenv("COS_SECRET_ID") and os.getenv("COS_SECRET_KEY")):
        print("\n[WARNING] COS_SECRET_ID or COS_SECRET_KEY not found in environment.")
        print("Local upload will likely fail unless you are in a trusted Tencent Cloud environment.")
        print("Please export these variables or edit the script to include them.\n")

    filename = f"test_img_{int(time.time())}.gif"
    file_data = create_dummy_image()
    content_type = "image/gif"
    user_id = "test_script_user"

    print(f">>> Attempting to upload {filename} ({len(file_data)} bytes)...")
    
    try:
        result = upload_file_stream(user_id, filename, file_data, content_type)
        print("\n>>> Upload Result:")
        print(result)
        
        signed_url = result.get("signed_url")
        if not signed_url:
            print("\n[FAIL] No signed_url found in result!")
            return

        print(f"\n>>> Verifying signed_url: {signed_url}")
        try:
            with urllib.request.urlopen(signed_url) as response:
                if response.status == 200:
                    print(f"[SUCCESS] URL accessed successfully. Status: {response.status}")
                    print(f"Content-Type: {response.headers.get('Content-Type')}")
                    print(f"Content-Length: {response.headers.get('Content-Length')}")
                else:
                    print(f"[FAIL] URL returned status: {response.status}")
        except urllib.error.HTTPError as e:
             print(f"[FAIL] HTTP Error accessing URL: {e.code} - {e.reason}")
        except urllib.error.URLError as e:
             print(f"[FAIL] URL Error: {e.reason}")

    except Exception as e:
        print(f"\n[ERROR] Exception during upload: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_test()
