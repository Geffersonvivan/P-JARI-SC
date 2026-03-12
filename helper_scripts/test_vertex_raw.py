import os
import sys
from pathlib import Path

# Add project root to sys.path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, '.env'))

from google.cloud import discoveryengine_v1 as discoveryengine

def test_vertex_snippets():
    project_id = os.environ.get('VERTEX_PROJECT_ID')
    location = os.environ.get('VERTEX_LOCATION', 'global')
    data_store_id = os.environ.get('VERTEX_DATA_STORE_ID')
    
    print(f"Project ID: {project_id}")
    print(f"Data Store ID: {data_store_id}")
    
    client = discoveryengine.SearchServiceClient()
    serving_config = client.serving_config_path(
        project=project_id,
        location=location,
        data_store=data_store_id,
        serving_config="default_config",
    )
    
    query = "Parecer 381/2022"
    
    request = discoveryengine.SearchRequest(
        serving_config=serving_config,
        query=query,
        page_size=2,
        content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
            snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                return_snippet=True
            )
        )
    )
    
    response = client.search(request)
    
    print("--- RAW RESPONSE EXACT ---")
    for i, result in enumerate(response.results):
        print(f"\nRESULTADO {i+1}:")
        document_data = result.document.derived_struct_data
        
        snippets = document_data.get("snippets", [])
        if snippets:
            for snip in snippets:
                print(f"SNIPPET: {snip.get('snippet', '')}")
        else:
            print("NO SNIPPETS FOUND")

if __name__ == '__main__':
    test_vertex_snippets()
