(= (loadOmegaClawPlugin)
   (progn
     (add-atom &self
       (= (get-mcp-tools)
          (py-call (mcp_client.get_tools_as_list))))
     (add-atom &self
       (= (call-mcp $tool-name $arguments)
          (py-call (mcp_client.call_tool $tool-name $arguments))))
     (add-skill get-mcp-tools "Get all available MCP tools with their descriptions" ())
     (add-skill call-mcp "Call an MCP tool with parameters encoded as a JSON object" (tool_name parameters_as_json_string))
     (add-atom &self
       (= (prompt-extension mcp-tools)
          (let $tools (py-call (mcp_client.get_tools_prompt))
            (if (== $tools "") (empty) $tools))))
     ()))
