import argparse
import os
import shutil

import d4j_client


def checkout_project(project_name, version):
    """Check out a buggy Defects4J version via the defects4j_docker_web service."""
    folder_name = d4j_client.folder_name_for(project_name, version)

    # The workspace is bind-mounted into the container; clearing it on the host
    # clears the container's view, so `defects4j checkout` gets a clean target.
    workspace_dir = os.path.join(d4j_client.HOST_WORKSPACE, folder_name)
    if os.path.exists(workspace_dir):
        shutil.rmtree(workspace_dir)

    rc, stdout, stderr = d4j_client.checkout(project_name, version, folder_name)
    if rc == 0:
        print("Checkout completed successfully!")
    else:
        print(f"Checkout failed with error: {stderr}")


parser = argparse.ArgumentParser()
parser.add_argument("project")
parser.add_argument("index")
args = parser.parse_args()

checkout_project(args.project, args.index)
