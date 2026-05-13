import json
import time
import urllib.request
import urllib.parse
import websocket

COMFY_URL = "http://172.24.224.1:8189"
CLIENT_ID = "batch_inventory_generator"

workflow_path = "inventory_item_workflow.json"

with open(workflow_path, "r", encoding="utf-8") as f:
    workflow = json.load(f)

def queue_prompt(prompt):
    data = json.dumps({
        "prompt": prompt,
        "client_id": CLIENT_ID
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{COMFY_URL}/prompt",
        data=data,
        headers={"Content-Type": "application/json"}
    )

    return json.loads(urllib.request.urlopen(req).read())


def wait_for_prompt(prompt_id):
    ws = websocket.WebSocket()
    ws.connect(f"ws://172.24.224.1:8189/ws?clientId={CLIENT_ID}")

    while True:
        msg = json.loads(ws.recv())

        if msg["type"] == "executing":
            data = msg["data"]

            if data["prompt_id"] == prompt_id and data["node"] is None:
                break

    ws.close()


def generate(object_name, object_description):
    # IMPORTANT:
    # Replace these node IDs with the actual node IDs from your workflow.
    # Open your workflow JSON and find the text prompt node.
    
    POSITIVE_PROMPT_NODE = "6"
    INPUT_LOAD_NODE = "90"
    OUTPUT_SAVE_NODE = "9"

    prompt_text = f"""
High-quality inventory item render of this {object_description}, matching a cozy handmade educational adventure game aesthetic.
Object centered, isolated on a warm cream background.
Miniature scale, tactile handcrafted realism, soft studio lighting, gentle shadows, warm muted colors, slightly worn materials, charming storybook feel.
Clean readable silhouette, game asset, inventory icon, high detail, no text, no labels, no extra objects.
"""

    workflow[POSITIVE_PROMPT_NODE]["inputs"]["text"] = prompt_text
    workflow[INPUT_LOAD_NODE]["inputs"]["image"] = f"D:/wonky-studio/temp/{object_name}.png"
    workflow[OUTPUT_SAVE_NODE]["inputs"]["filename_prefix"] = f"inventory/{object_name}"

    result = queue_prompt(workflow)
    prompt_id = result["prompt_id"]

    wait_for_prompt(prompt_id)

    print(f"Generated: {object_name}")


items = [
    ("clock", "alarm clock"),
]

for name, desc in items:
    generate(name, desc)
    time.sleep(0.5)