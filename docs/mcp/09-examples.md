# Model Context Protocol (MCP) - Examples

## Table of Contents
- [Overview](#overview)
- [Complete Server Examples](#complete-server-examples)
- [Complete Client Examples](#complete-client-examples)
- [Real-World Implementations](#real-world-implementations)
- [Integration Examples](#integration-examples)
- [Advanced Patterns](#advanced-patterns)
- [Troubleshooting Common Issues](#troubleshooting-common-issues)

## Overview

This document provides practical examples of MCP implementations, from simple servers and clients to complex real-world integrations. Each example includes complete, runnable code with explanations.

## Complete Server Examples

### 1. File System Server

A complete MCP server that provides file system access with security controls.

```typescript
// filesystem-server.ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import * as fs from "fs/promises";
import * as path from "path";
import { z } from "zod";

const server = new Server(
  {
    name: "filesystem-server",
    version: "1.0.0",
  },
  {
    capabilities: {
      resources: {},
      tools: {},
    },
  }
);

// Configuration
const ALLOWED_DIRECTORIES = [
  process.env.HOME + "/Documents",
  process.env.HOME + "/Desktop",
];

// Helper to validate paths
function isPathAllowed(filePath: string): boolean {
  const absolutePath = path.resolve(filePath);
  return ALLOWED_DIRECTORIES.some(dir => 
    absolutePath.startsWith(path.resolve(dir))
  );
}

// List available resources (files)
server.setRequestHandler("resources/list", async () => {
  const resources = [];
  
  for (const dir of ALLOWED_DIRECTORIES) {
    try {
      const files = await fs.readdir(dir, { withFileTypes: true });
      for (const file of files) {
        if (file.isFile()) {
          resources.push({
            uri: `file://${path.join(dir, file.name)}`,
            name: file.name,
            mimeType: getMimeType(file.name),
          });
        }
      }
    } catch (error) {
      // Directory might not exist
    }
  }
  
  return { resources };
});

// Read file content
server.setRequestHandler("resources/read", async (request) => {
  const { uri } = request.params;
  const filePath = uri.replace("file://", "");
  
  if (!isPathAllowed(filePath)) {
    throw new Error("Access denied: Path not allowed");
  }
  
  const content = await fs.readFile(filePath, "utf-8");
  
  return {
    contents: [
      {
        uri,
        mimeType: getMimeType(filePath),
        text: content,
      },
    ],
  };
});

// File manipulation tools
const tools = [
  {
    name: "create_file",
    description: "Create a new file",
    inputSchema: z.object({
      path: z.string().describe("File path"),
      content: z.string().describe("File content"),
    }),
  },
  {
    name: "append_to_file",
    description: "Append content to an existing file",
    inputSchema: z.object({
      path: z.string().describe("File path"),
      content: z.string().describe("Content to append"),
    }),
  },
  {
    name: "delete_file",
    description: "Delete a file",
    inputSchema: z.object({
      path: z.string().describe("File path"),
    }),
  },
  {
    name: "list_directory",
    description: "List contents of a directory",
    inputSchema: z.object({
      path: z.string().describe("Directory path"),
    }),
  },
];

// List available tools
server.setRequestHandler("tools/list", async () => {
  return {
    tools: tools.map(tool => ({
      name: tool.name,
      description: tool.description,
      inputSchema: zodToJsonSchema(tool.inputSchema),
    })),
  };
});

// Execute tools
server.setRequestHandler("tools/call", async (request) => {
  const { name, arguments: args } = request.params;
  
  // Validate path for all tools
  if (args.path && !isPathAllowed(args.path)) {
    throw new Error("Access denied: Path not allowed");
  }
  
  switch (name) {
    case "create_file": {
      await fs.writeFile(args.path, args.content);
      return {
        content: [
          {
            type: "text",
            text: `File created: ${args.path}`,
          },
        ],
      };
    }
    
    case "append_to_file": {
      await fs.appendFile(args.path, args.content);
      return {
        content: [
          {
            type: "text",
            text: `Content appended to: ${args.path}`,
          },
        ],
      };
    }
    
    case "delete_file": {
      await fs.unlink(args.path);
      return {
        content: [
          {
            type: "text",
            text: `File deleted: ${args.path}`,
          },
        ],
      };
    }
    
    case "list_directory": {
      const files = await fs.readdir(args.path, { withFileTypes: true });
      const listing = files.map(file => ({
        name: file.name,
        type: file.isDirectory() ? "directory" : "file",
      }));
      
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(listing, null, 2),
          },
        ],
      };
    }
    
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
});

// Helper functions
function getMimeType(filename: string): string {
  const ext = path.extname(filename).toLowerCase();
  const mimeTypes = {
    ".txt": "text/plain",
    ".json": "application/json",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".py": "text/x-python",
    ".md": "text/markdown",
    ".html": "text/html",
    ".css": "text/css",
  };
  return mimeTypes[ext] || "application/octet-stream";
}

function zodToJsonSchema(schema: z.ZodSchema): any {
  // Simple conversion - in production use a proper library
  return {
    type: "object",
    properties: Object.fromEntries(
      Object.entries(schema.shape).map(([key, value]) => [
        key,
        { type: "string", description: value._def.description },
      ])
    ),
    required: Object.keys(schema.shape),
  };
}

// Start server
const transport = new StdioServerTransport();
server.connect(transport).then(() => {
  console.error("Filesystem MCP server running");
});
```

### 2. Database Server

An MCP server that provides database access with query capabilities.

```python
# database_server.py
import asyncio
import json
import sqlite3
from typing import List, Dict, Any
from mcp import Server, Resource, Tool
from mcp.server.stdio import StdioServerTransport
from mcp.types import TextContent, ToolResult

class DatabaseServer:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.server = Server(
            name="database-server",
            version="1.0.0"
        )
        self.setup_handlers()
    
    def setup_handlers(self):
        @self.server.list_resources()
        async def list_resources() -> List[Resource]:
            """List available database tables as resources"""
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get all tables
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = cursor.fetchall()
            conn.close()
            
            return [
                Resource(
                    uri=f"db://{self.db_path}/{table[0]}",
                    name=f"Table: {table[0]}",
                    mime_type="application/json"
                )
                for table in tables
            ]
        
        @self.server.read_resource()
        async def read_resource(uri: str) -> Dict[str, Any]:
            """Read table schema and sample data"""
            # Parse URI
            parts = uri.replace("db://", "").split("/")
            table_name = parts[-1]
            
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get table schema
            cursor.execute(f"PRAGMA table_info({table_name})")
            schema = [dict(row) for row in cursor.fetchall()]
            
            # Get sample data
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
            sample_data = [dict(row) for row in cursor.fetchall()]
            
            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row_count = cursor.fetchone()[0]
            
            conn.close()
            
            result = {
                "table": table_name,
                "schema": schema,
                "row_count": row_count,
                "sample_data": sample_data
            }
            
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mime_type": "application/json",
                        "text": json.dumps(result, indent=2)
                    }
                ]
            }
        
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            """List available database tools"""
            return [
                Tool(
                    name="query",
                    description="Execute a SELECT query",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "sql": {
                                "type": "string",
                                "description": "SELECT query to execute"
                            },
                            "parameters": {
                                "type": "array",
                                "description": "Query parameters",
                                "items": {"type": ["string", "number", "null"]}
                            }
                        },
                        "required": ["sql"]
                    }
                ),
                Tool(
                    name="execute",
                    description="Execute INSERT, UPDATE, or DELETE",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "sql": {
                                "type": "string",
                                "description": "SQL statement to execute"
                            },
                            "parameters": {
                                "type": "array",
                                "description": "Statement parameters",
                                "items": {"type": ["string", "number", "null"]}
                            }
                        },
                        "required": ["sql"]
                    }
                ),
                Tool(
                    name="create_table",
                    description="Create a new table",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "table_name": {
                                "type": "string",
                                "description": "Name of the table"
                            },
                            "columns": {
                                "type": "array",
                                "description": "Column definitions",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "type": {"type": "string"},
                                        "primary_key": {"type": "boolean"},
                                        "not_null": {"type": "boolean"}
                                    },
                                    "required": ["name", "type"]
                                }
                            }
                        },
                        "required": ["table_name", "columns"]
                    }
                )
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> ToolResult:
            """Execute database tools"""
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            try:
                if name == "query":
                    # Validate it's a SELECT query
                    sql = arguments["sql"].strip().upper()
                    if not sql.startswith("SELECT"):
                        raise ValueError("Only SELECT queries allowed")
                    
                    # Execute query
                    params = arguments.get("parameters", [])
                    cursor.execute(arguments["sql"], params)
                    
                    # Fetch results
                    results = [dict(row) for row in cursor.fetchall()]
                    
                    return ToolResult(
                        content=[
                            TextContent(
                                text=json.dumps({
                                    "row_count": len(results),
                                    "results": results
                                }, indent=2)
                            )
                        ]
                    )
                
                elif name == "execute":
                    # Execute statement
                    params = arguments.get("parameters", [])
                    cursor.execute(arguments["sql"], params)
                    conn.commit()
                    
                    return ToolResult(
                        content=[
                            TextContent(
                                text=f"Executed successfully. Rows affected: {cursor.rowcount}"
                            )
                        ]
                    )
                
                elif name == "create_table":
                    # Build CREATE TABLE statement
                    columns = []
                    for col in arguments["columns"]:
                        col_def = f"{col['name']} {col['type']}"
                        if col.get("primary_key"):
                            col_def += " PRIMARY KEY"
                        if col.get("not_null"):
                            col_def += " NOT NULL"
                        columns.append(col_def)
                    
                    sql = f"CREATE TABLE {arguments['table_name']} ({', '.join(columns)})"
                    cursor.execute(sql)
                    conn.commit()
                    
                    return ToolResult(
                        content=[
                            TextContent(
                                text=f"Table '{arguments['table_name']}' created successfully"
                            )
                        ]
                    )
                
                else:
                    raise ValueError(f"Unknown tool: {name}")
                    
            except Exception as e:
                return ToolResult(
                    content=[
                        TextContent(text=f"Error: {str(e)}")
                    ],
                    is_error=True
                )
            finally:
                conn.close()
    
    async def run(self):
        transport = StdioServerTransport()
        await self.server.connect(transport)
        await self.server.run()

# Initialize with sample database
def init_sample_db(db_path: str):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create sample tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER DEFAULT 0
        )
    """)
    
    # Insert sample data
    cursor.executemany(
        "INSERT OR IGNORE INTO users (name, email) VALUES (?, ?)",
        [
            ("Alice Smith", "alice@example.com"),
            ("Bob Johnson", "bob@example.com"),
            ("Charlie Brown", "charlie@example.com")
        ]
    )
    
    cursor.executemany(
        "INSERT OR IGNORE INTO products (name, price, stock) VALUES (?, ?, ?)",
        [
            ("Widget", 9.99, 100),
            ("Gadget", 19.99, 50),
            ("Doohickey", 14.99, 75)
        ]
    )
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    db_path = "sample.db"
    init_sample_db(db_path)
    
    server = DatabaseServer(db_path)
    asyncio.run(server.run())
```

### 3. API Integration Server

An MCP server that integrates with external APIs.

```typescript
// api-server.ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { HttpServerTransport } from "@modelcontextprotocol/sdk/server/http.js";
import axios from "axios";
import { z } from "zod";

const server = new Server(
  {
    name: "api-integration-server",
    version: "1.0.0",
  },
  {
    capabilities: {
      resources: {},
      tools: {},
      prompts: {},
    },
  }
);

// API configurations
const APIs = {
  weather: {
    baseUrl: "https://api.openweathermap.org/data/2.5",
    apiKey: process.env.OPENWEATHER_API_KEY,
  },
  github: {
    baseUrl: "https://api.github.com",
    token: process.env.GITHUB_TOKEN,
  },
};

// Resources for API documentation
server.setRequestHandler("resources/list", async () => {
  return {
    resources: [
      {
        uri: "api://weather/docs",
        name: "Weather API Documentation",
        mimeType: "text/markdown",
      },
      {
        uri: "api://github/docs",
        name: "GitHub API Documentation",
        mimeType: "text/markdown",
      },
    ],
  };
});

server.setRequestHandler("resources/read", async (request) => {
  const { uri } = request.params;
  
  const docs = {
    "api://weather/docs": `# Weather API
    
Available endpoints:
- Get current weather: \`weather?q={city}\`
- Get forecast: \`forecast?q={city}\`

Example usage with the MCP tool:
- Tool: get_weather
- Arguments: { "city": "London" }`,
    
    "api://github/docs": `# GitHub API
    
Available endpoints:
- Get user repos: \`/users/{username}/repos\`
- Get repo info: \`/repos/{owner}/{repo}\`
- Create issue: \`/repos/{owner}/{repo}/issues\`

Example usage with MCP tools:
- Tool: github_user_repos
- Arguments: { "username": "octocat" }`,
  };
  
  return {
    contents: [
      {
        uri,
        mimeType: "text/markdown",
        text: docs[uri] || "Documentation not found",
      },
    ],
  };
});

// Tool definitions
const weatherTools = [
  {
    name: "get_weather",
    description: "Get current weather for a city",
    inputSchema: z.object({
      city: z.string().describe("City name"),
      units: z.enum(["metric", "imperial"]).default("metric"),
    }),
  },
  {
    name: "get_forecast",
    description: "Get 5-day weather forecast",
    inputSchema: z.object({
      city: z.string().describe("City name"),
      units: z.enum(["metric", "imperial"]).default("metric"),
    }),
  },
];

const githubTools = [
  {
    name: "github_user_repos",
    description: "Get repositories for a GitHub user",
    inputSchema: z.object({
      username: z.string().describe("GitHub username"),
      sort: z.enum(["created", "updated", "pushed", "full_name"]).optional(),
    }),
  },
  {
    name: "github_repo_info",
    description: "Get information about a GitHub repository",
    inputSchema: z.object({
      owner: z.string().describe("Repository owner"),
      repo: z.string().describe("Repository name"),
    }),
  },
  {
    name: "github_create_issue",
    description: "Create an issue in a GitHub repository",
    inputSchema: z.object({
      owner: z.string().describe("Repository owner"),
      repo: z.string().describe("Repository name"),
      title: z.string().describe("Issue title"),
      body: z.string().describe("Issue body"),
      labels: z.array(z.string()).optional(),
    }),
  },
];

// List all tools
server.setRequestHandler("tools/list", async () => {
  return {
    tools: [...weatherTools, ...githubTools].map(tool => ({
      name: tool.name,
      description: tool.description,
      inputSchema: zodToJsonSchema(tool.inputSchema),
    })),
  };
});

// Execute tools
server.setRequestHandler("tools/call", async (request) => {
  const { name, arguments: args } = request.params;
  
  try {
    // Weather API tools
    if (name === "get_weather") {
      const response = await axios.get(
        `${APIs.weather.baseUrl}/weather`,
        {
          params: {
            q: args.city,
            units: args.units,
            appid: APIs.weather.apiKey,
          },
        }
      );
      
      const data = response.data;
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              city: data.name,
              country: data.sys.country,
              temperature: data.main.temp,
              feels_like: data.main.feels_like,
              description: data.weather[0].description,
              humidity: data.main.humidity,
              wind_speed: data.wind.speed,
            }, null, 2),
          },
        ],
      };
    }
    
    if (name === "get_forecast") {
      const response = await axios.get(
        `${APIs.weather.baseUrl}/forecast`,
        {
          params: {
            q: args.city,
            units: args.units,
            appid: APIs.weather.apiKey,
          },
        }
      );
      
      const forecasts = response.data.list.slice(0, 5).map(item => ({
        datetime: item.dt_txt,
        temperature: item.main.temp,
        description: item.weather[0].description,
      }));
      
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(forecasts, null, 2),
          },
        ],
      };
    }
    
    // GitHub API tools
    if (name === "github_user_repos") {
      const response = await axios.get(
        `${APIs.github.baseUrl}/users/${args.username}/repos`,
        {
          headers: {
            Authorization: `token ${APIs.github.token}`,
          },
          params: {
            sort: args.sort,
            per_page: 10,
          },
        }
      );
      
      const repos = response.data.map(repo => ({
        name: repo.name,
        description: repo.description,
        stars: repo.stargazers_count,
        language: repo.language,
        url: repo.html_url,
      }));
      
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(repos, null, 2),
          },
        ],
      };
    }
    
    if (name === "github_repo_info") {
      const response = await axios.get(
        `${APIs.github.baseUrl}/repos/${args.owner}/${args.repo}`,
        {
          headers: {
            Authorization: `token ${APIs.github.token}`,
          },
        }
      );
      
      const info = {
        name: response.data.name,
        description: response.data.description,
        stars: response.data.stargazers_count,
        forks: response.data.forks_count,
        open_issues: response.data.open_issues_count,
        language: response.data.language,
        created_at: response.data.created_at,
        updated_at: response.data.updated_at,
      };
      
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(info, null, 2),
          },
        ],
      };
    }
    
    if (name === "github_create_issue") {
      const response = await axios.post(
        `${APIs.github.baseUrl}/repos/${args.owner}/${args.repo}/issues`,
        {
          title: args.title,
          body: args.body,
          labels: args.labels,
        },
        {
          headers: {
            Authorization: `token ${APIs.github.token}`,
          },
        }
      );
      
      return {
        content: [
          {
            type: "text",
            text: `Issue created: ${response.data.html_url}`,
          },
        ],
      };
    }
    
    throw new Error(`Unknown tool: ${name}`);
    
  } catch (error) {
    return {
      content: [
        {
          type: "text",
          text: `Error: ${error.message}`,
        },
      ],
      isError: true,
    };
  }
});

// Prompts for common API tasks
server.setRequestHandler("prompts/list", async () => {
  return {
    prompts: [
      {
        name: "weather_report",
        description: "Generate a weather report for multiple cities",
        arguments: [
          {
            name: "cities",
            description: "Comma-separated list of cities",
            required: true,
          },
        ],
      },
      {
        name: "github_activity",
        description: "Analyze GitHub user activity",
        arguments: [
          {
            name: "username",
            description: "GitHub username",
            required: true,
          },
        ],
      },
    ],
  };
});

server.setRequestHandler("prompts/get", async (request) => {
  const { name, arguments: args } = request.params;
  
  if (name === "weather_report") {
    const cities = args.cities.split(",").map(c => c.trim());
    return {
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `Please generate a comprehensive weather report for the following cities: ${cities.join(", ")}. 
            
Use the get_weather tool for each city and create a summary that includes:
1. Current conditions for each city
2. Temperature comparisons
3. Any weather warnings or notable conditions
4. Recommendations for travelers`,
          },
        },
      ],
    };
  }
  
  if (name === "github_activity") {
    return {
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `Please analyze the GitHub activity for user: ${args.username}
            
Use the github_user_repos tool to get their repositories and provide:
1. Overview of their most popular repositories
2. Primary programming languages used
3. Recent activity summary
4. Interesting projects worth highlighting`,
          },
        },
      ],
    };
  }
  
  throw new Error(`Unknown prompt: ${name}`);
});

// Helper function
function zodToJsonSchema(schema: z.ZodSchema): any {
  // Simplified - use a proper library in production
  return {
    type: "object",
    properties: Object.fromEntries(
      Object.entries(schema.shape).map(([key, value]) => [
        key,
        { 
          type: value._def.typeName === "ZodEnum" ? "string" : "string",
          enum: value._def.values,
          description: value._def.description,
        },
      ])
    ),
    required: Object.keys(schema.shape).filter(
      key => !schema.shape[key].isOptional()
    ),
  };
}

// Start HTTP server
const transport = new HttpServerTransport({
  port: 3000,
});

server.connect(transport).then(() => {
  console.log("API Integration MCP server running on port 3000");
});
```

## Complete Client Examples

### 1. Interactive CLI Client

A command-line client that interacts with MCP servers.

```python
# cli_client.py
import asyncio
import json
import sys
from typing import Optional
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from mcp import Client
from mcp.client.stdio import StdioClientTransport

class InteractiveMCPClient:
    def __init__(self):
        self.client = Client(
            name="interactive-cli",
            version="1.0.0"
        )
        self.connected = False
        self.resources = []
        self.tools = []
        self.prompts = []
    
    async def connect(self, command: str, args: list):
        """Connect to an MCP server"""
        try:
            transport = StdioClientTransport(command=command, args=args)
            await self.client.connect(transport)
            self.connected = True
            
            # Cache available capabilities
            await self.refresh_capabilities()
            
            print(f"Connected to server: {self.client.server_info.name}")
            print(f"Server version: {self.client.server_info.version}")
            
        except Exception as e:
            print(f"Failed to connect: {e}")
            self.connected = False
    
    async def refresh_capabilities(self):
        """Refresh cached capabilities"""
        try:
            self.resources = await self.client.list_resources()
            self.tools = await self.client.list_tools()
            self.prompts = await self.client.list_prompts()
        except:
            # Server might not support all capabilities
            pass
    
    async def list_resources(self):
        """List available resources"""
        if not self.resources:
            print("No resources available")
            return
        
        print("\nAvailable Resources:")
        for i, resource in enumerate(self.resources, 1):
            print(f"{i}. {resource.name} ({resource.uri})")
            if resource.description:
                print(f"   {resource.description}")
    
    async def read_resource(self, uri: str):
        """Read a specific resource"""
        try:
            content = await self.client.read_resource(uri)
            print(f"\nResource: {uri}")
            print("-" * 50)
            for item in content.contents:
                if item.text:
                    print(item.text)
                elif item.blob:
                    print(f"[Binary data: {len(item.blob)} bytes]")
        except Exception as e:
            print(f"Error reading resource: {e}")
    
    async def list_tools(self):
        """List available tools"""
        if not self.tools:
            print("No tools available")
            return
        
        print("\nAvailable Tools:")
        for i, tool in enumerate(self.tools, 1):
            print(f"{i}. {tool.name}")
            if tool.description:
                print(f"   {tool.description}")
            if hasattr(tool, 'input_schema'):
                print(f"   Parameters: {json.dumps(tool.input_schema, indent=6)}")
    
    async def call_tool(self, name: str, args_str: str):
        """Call a tool with arguments"""
        try:
            # Parse arguments
            args = json.loads(args_str) if args_str else {}
            
            # Call tool
            result = await self.client.call_tool(name, args)
            
            print(f"\nTool Result: {name}")
            print("-" * 50)
            for content in result.content:
                if content.text:
                    print(content.text)
                elif hasattr(content, 'data'):
                    print(f"[Image data: {content.mime_type}]")
            
            if result.is_error:
                print("(Error occurred during execution)")
                
        except json.JSONDecodeError:
            print("Invalid JSON arguments")
        except Exception as e:
            print(f"Error calling tool: {e}")
    
    async def list_prompts(self):
        """List available prompts"""
        if not self.prompts:
            print("No prompts available")
            return
        
        print("\nAvailable Prompts:")
        for i, prompt_info in enumerate(self.prompts, 1):
            print(f"{i}. {prompt_info.name}")
            if prompt_info.description:
                print(f"   {prompt_info.description}")
            if prompt_info.arguments:
                for arg in prompt_info.arguments:
                    req = " (required)" if arg.required else ""
                    print(f"   - {arg.name}: {arg.description}{req}")
    
    async def get_prompt(self, name: str, args_str: str):
        """Get a prompt with arguments"""
        try:
            # Parse arguments
            args = json.loads(args_str) if args_str else {}
            
            # Get prompt
            result = await self.client.get_prompt(name, args)
            
            print(f"\nPrompt: {name}")
            if result.description:
                print(f"Description: {result.description}")
            print("-" * 50)
            
            for message in result.messages:
                print(f"\n[{message.role}]:")
                if message.content.text:
                    print(message.content.text)
                    
        except json.JSONDecodeError:
            print("Invalid JSON arguments")
        except Exception as e:
            print(f"Error getting prompt: {e}")
    
    async def interactive_loop(self):
        """Main interactive loop"""
        # Command completer
        commands = [
            "help", "connect", "disconnect", "resources", "read",
            "tools", "call", "prompts", "prompt", "refresh", "exit"
        ]
        completer = WordCompleter(commands)
        
        print("MCP Interactive Client")
        print("Type 'help' for available commands")
        
        while True:
            try:
                # Get user input
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: prompt("mcp> ", completer=completer)
                )
                
                if not user_input.strip():
                    continue
                
                # Parse command
                parts = user_input.strip().split(maxsplit=2)
                command = parts[0].lower()
                
                # Execute command
                if command == "help":
                    self.show_help()
                
                elif command == "connect":
                    if len(parts) < 2:
                        print("Usage: connect <command> [args...]")
                    else:
                        cmd = parts[1]
                        args = parts[2].split() if len(parts) > 2 else []
                        await self.connect(cmd, args)
                
                elif command == "disconnect":
                    if self.connected:
                        await self.client.disconnect()
                        self.connected = False
                        print("Disconnected")
                    else:
                        print("Not connected")
                
                elif command == "resources":
                    if not self.connected:
                        print("Not connected to a server")
                    else:
                        await self.list_resources()
                
                elif command == "read":
                    if not self.connected:
                        print("Not connected to a server")
                    elif len(parts) < 2:
                        print("Usage: read <resource-uri>")
                    else:
                        await self.read_resource(parts[1])
                
                elif command == "tools":
                    if not self.connected:
                        print("Not connected to a server")
                    else:
                        await self.list_tools()
                
                elif command == "call":
                    if not self.connected:
                        print("Not connected to a server")
                    elif len(parts) < 2:
                        print("Usage: call <tool-name> [json-args]")
                    else:
                        tool_name = parts[1]
                        args = parts[2] if len(parts) > 2 else ""
                        await self.call_tool(tool_name, args)
                
                elif command == "prompts":
                    if not self.connected:
                        print("Not connected to a server")
                    else:
                        await self.list_prompts()
                
                elif command == "prompt":
                    if not self.connected:
                        print("Not connected to a server")
                    elif len(parts) < 2:
                        print("Usage: prompt <prompt-name> [json-args]")
                    else:
                        prompt_name = parts[1]
                        args = parts[2] if len(parts) > 2 else ""
                        await self.get_prompt(prompt_name, args)
                
                elif command == "refresh":
                    if not self.connected:
                        print("Not connected to a server")
                    else:
                        await self.refresh_capabilities()
                        print("Capabilities refreshed")
                
                elif command == "exit":
                    if self.connected:
                        await self.client.disconnect()
                    print("Goodbye!")
                    break
                
                else:
                    print(f"Unknown command: {command}")
                    print("Type 'help' for available commands")
                    
            except KeyboardInterrupt:
                print("\nUse 'exit' to quit")
            except Exception as e:
                print(f"Error: {e}")
    
    def show_help(self):
        """Show help information"""
        help_text = """
Available Commands:
  connect <command> [args...]  - Connect to an MCP server
  disconnect                   - Disconnect from server
  resources                    - List available resources
  read <uri>                   - Read a resource
  tools                        - List available tools
  call <tool> [json-args]      - Call a tool
  prompts                      - List available prompts
  prompt <name> [json-args]    - Get a prompt
  refresh                      - Refresh server capabilities
  exit                         - Exit the client
  help                         - Show this help

Examples:
  connect python server.py
  connect node ./server.js --debug
  read file:///path/to/file.txt
  call create_file '{"path": "/tmp/test.txt", "content": "Hello"}'
  prompt weather_report '{"cities": "London, Paris, Berlin"}'
"""
        print(help_text)

async def main():
    client = InteractiveMCPClient()
    
    # Connect to server if provided as command line argument
    if len(sys.argv) > 1:
        await client.connect(sys.argv[1], sys.argv[2:])
    
    # Run interactive loop
    await client.interactive_loop()

if __name__ == "__main__":
    asyncio.run(main())
```

### 2. Web Dashboard Client

A web-based client with a dashboard interface.

```typescript
// web-client/src/MCPDashboard.tsx
import React, { useState, useEffect } from 'react';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { WebSocketClientTransport } from '@modelcontextprotocol/sdk/client/websocket.js';

interface Resource {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
}

interface Tool {
  name: string;
  description?: string;
  inputSchema?: any;
}

interface ServerInfo {
  name: string;
  version: string;
  capabilities: any;
}

const MCPDashboard: React.FC = () => {
  const [client, setClient] = useState<Client | null>(null);
  const [connected, setConnected] = useState(false);
  const [serverInfo, setServerInfo] = useState<ServerInfo | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [selectedResource, setSelectedResource] = useState<string | null>(null);
  const [resourceContent, setResourceContent] = useState<string>('');
  const [selectedTool, setSelectedTool] = useState<string | null>(null);
  const [toolArgs, setToolArgs] = useState<string>('{}');
  const [toolResult, setToolResult] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');

  // Connect to MCP server
  const connect = async (url: string) => {
    try {
      setLoading(true);
      setError('');
      
      const newClient = new Client({
        name: 'web-dashboard',
        version: '1.0.0',
      });
      
      const transport = new WebSocketClientTransport(url);
      await newClient.connect(transport);
      
      setClient(newClient);
      setConnected(true);
      
      // Get server info
      const info = newClient.serverInfo;
      setServerInfo(info);
      
      // Load initial data
      await loadCapabilities(newClient);
      
    } catch (err) {
      setError(`Connection failed: ${err.message}`);
      setConnected(false);
    } finally {
      setLoading(false);
    }
  };

  // Load server capabilities
  const loadCapabilities = async (client: Client) => {
    try {
      // Load resources
      const resourceList = await client.request('resources/list');
      setResources(resourceList.resources || []);
      
      // Load tools
      const toolList = await client.request('tools/list');
      setTools(toolList.tools || []);
      
    } catch (err) {
      console.error('Failed to load capabilities:', err);
    }
  };

  // Read a resource
  const readResource = async (uri: string) => {
    if (!client) return;
    
    try {
      setLoading(true);
      setError('');
      
      const content = await client.request('resources/read', { uri });
      const text = content.contents?.[0]?.text || '';
      setResourceContent(text);
      
    } catch (err) {
      setError(`Failed to read resource: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Call a tool
  const callTool = async () => {
    if (!client || !selectedTool) return;
    
    try {
      setLoading(true);
      setError('');
      setToolResult('');
      
      const args = JSON.parse(toolArgs);
      const result = await client.request('tools/call', {
        name: selectedTool,
        arguments: args,
      });
      
      const text = result.content?.[0]?.text || JSON.stringify(result);
      setToolResult(text);
      
    } catch (err) {
      setError(`Tool execution failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mcp-dashboard">
      <header>
        <h1>MCP Dashboard</h1>
        {connected ? (
          <div className="server-info">
            <span className="status connected">● Connected</span>
            <span>{serverInfo?.name} v{serverInfo?.version}</span>
          </div>
        ) : (
          <div className="connection-form">
            <input
              type="text"
              placeholder="ws://localhost:3000"
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  connect(e.currentTarget.value);
                }
              }}
            />
            <button onClick={(e) => {
              const input = e.currentTarget.previousSibling as HTMLInputElement;
              connect(input.value);
            }}>
              Connect
            </button>
          </div>
        )}
      </header>

      {error && (
        <div className="error-banner">
          {error}
        </div>
      )}

      {connected && (
        <div className="dashboard-content">
          <div className="panel resources-panel">
            <h2>Resources</h2>
            <div className="resource-list">
              {resources.map((resource) => (
                <div
                  key={resource.uri}
                  className={`resource-item ${selectedResource === resource.uri ? 'selected' : ''}`}
                  onClick={() => {
                    setSelectedResource(resource.uri);
                    readResource(resource.uri);
                  }}
                >
                  <div className="resource-name">{resource.name}</div>
                  <div className="resource-uri">{resource.uri}</div>
                  {resource.description && (
                    <div className="resource-desc">{resource.description}</div>
                  )}
                </div>
              ))}
            </div>
            
            {selectedResource && (
              <div className="resource-content">
                <h3>Content</h3>
                <pre>{resourceContent}</pre>
              </div>
            )}
          </div>

          <div className="panel tools-panel">
            <h2>Tools</h2>
            <div className="tool-list">
              {tools.map((tool) => (
                <div
                  key={tool.name}
                  className={`tool-item ${selectedTool === tool.name ? 'selected' : ''}`}
                  onClick={() => {
                    setSelectedTool(tool.name);
                    setToolArgs(JSON.stringify(
                      tool.inputSchema?.properties ? 
                        Object.fromEntries(
                          Object.entries(tool.inputSchema.properties).map(
                            ([key, schema]: [string, any]) => [key, schema.example || '']
                          )
                        ) : {},
                      null,
                      2
                    ));
                  }}
                >
                  <div className="tool-name">{tool.name}</div>
                  {tool.description && (
                    <div className="tool-desc">{tool.description}</div>
                  )}
                </div>
              ))}
            </div>
            
            {selectedTool && (
              <div className="tool-execution">
                <h3>Execute: {selectedTool}</h3>
                <div className="tool-args">
                  <label>Arguments (JSON):</label>
                  <textarea
                    value={toolArgs}
                    onChange={(e) => setToolArgs(e.target.value)}
                    rows={10}
                  />
                </div>
                <button 
                  onClick={callTool}
                  disabled={loading}
                >
                  {loading ? 'Executing...' : 'Execute Tool'}
                </button>
                
                {toolResult && (
                  <div className="tool-result">
                    <h4>Result</h4>
                    <pre>{toolResult}</pre>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// Styles
const styles = `
.mcp-dashboard {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
}

header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 30px;
  padding-bottom: 20px;
  border-bottom: 1px solid #e0e0e0;
}

h1 {
  margin: 0;
  font-size: 28px;
}

.server-info {
  display: flex;
  align-items: center;
  gap: 15px;
}

.status {
  display: flex;
  align-items: center;
  gap: 5px;
}

.status.connected {
  color: #4caf50;
}

.connection-form {
  display: flex;
  gap: 10px;
}

.connection-form input {
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  width: 250px;
}

.connection-form button {
  padding: 8px 16px;
  background: #2196f3;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.error-banner {
  background: #f44336;
  color: white;
  padding: 12px;
  border-radius: 4px;
  margin-bottom: 20px;
}

.dashboard-content {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.panel {
  background: #f5f5f5;
  border-radius: 8px;
  padding: 20px;
}

.panel h2 {
  margin-top: 0;
  margin-bottom: 15px;
  font-size: 20px;
}

.resource-list,
.tool-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 20px;
}

.resource-item,
.tool-item {
  background: white;
  padding: 12px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.resource-item:hover,
.tool-item:hover {
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.resource-item.selected,
.tool-item.selected {
  border: 2px solid #2196f3;
}

.resource-name,
.tool-name {
  font-weight: 600;
  margin-bottom: 4px;
}

.resource-uri {
  font-size: 12px;
  color: #666;
  font-family: monospace;
}

.resource-desc,
.tool-desc {
  font-size: 14px;
  color: #666;
  margin-top: 4px;
}

.resource-content,
.tool-execution {
  background: white;
  padding: 15px;
  border-radius: 4px;
}

.resource-content h3,
.tool-execution h3 {
  margin-top: 0;
  margin-bottom: 10px;
}

pre {
  background: #f0f0f0;
  padding: 10px;
  border-radius: 4px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.tool-args {
  margin-bottom: 15px;
}

.tool-args label {
  display: block;
  margin-bottom: 5px;
  font-weight: 600;
}

.tool-args textarea {
  width: 100%;
  padding: 8px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-family: monospace;
  font-size: 13px;
}

.tool-execution button {
  padding: 10px 20px;
  background: #4caf50;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 16px;
}

.tool-execution button:disabled {
  background: #cccccc;
  cursor: not-allowed;
}

.tool-result {
  margin-top: 20px;
}

.tool-result h4 {
  margin-bottom: 10px;
}
`;

export default MCPDashboard;
```

## Real-World Implementations

### 1. Claude Desktop Configuration

Example configuration for Claude Desktop with multiple MCP servers:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "node",
      "args": ["/path/to/filesystem-server.js"],
      "env": {
        "ALLOWED_DIRECTORIES": "/Users/username/Documents,/Users/username/Desktop"
      }
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "your-github-token"
      }
    },
    "database": {
      "command": "python",
      "args": ["/path/to/database-server.py"],
      "env": {
        "DATABASE_URL": "postgresql://localhost/mydb"
      }
    },
    "slack": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e", "SLACK_TOKEN=${SLACK_TOKEN}",
        "mcp/slack-server:latest"
      ]
    }
  }
}
```

### 2. VS Code Extension Integration

Example VS Code extension that integrates MCP:

```typescript
// extension.ts
import * as vscode from 'vscode';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

export function activate(context: vscode.ExtensionContext) {
  let mcpClient: Client | null = null;
  
  // Register MCP connection command
  const connectCommand = vscode.commands.registerCommand(
    'mcp.connect',
    async () => {
      const serverPath = await vscode.window.showInputBox({
        prompt: 'Enter MCP server command',
        placeHolder: 'node /path/to/server.js',
      });
      
      if (!serverPath) return;
      
      try {
        mcpClient = new Client({
          name: 'vscode-mcp',
          version: '1.0.0',
        });
        
        const [command, ...args] = serverPath.split(' ');
        const transport = new StdioClientTransport({ command, args });
        
        await mcpClient.connect(transport);
        
        vscode.window.showInformationMessage(
          `Connected to MCP server: ${mcpClient.serverInfo.name}`
        );
        
        // Register additional commands
        registerMCPCommands(context, mcpClient);
        
      } catch (error) {
        vscode.window.showErrorMessage(
          `Failed to connect: ${error.message}`
        );
      }
    }
  );
  
  context.subscriptions.push(connectCommand);
}

function registerMCPCommands(
  context: vscode.ExtensionContext,
  client: Client
) {
  // List resources command
  const listResourcesCommand = vscode.commands.registerCommand(
    'mcp.listResources',
    async () => {
      const resources = await client.request('resources/list');
      
      const items = resources.resources.map(r => ({
        label: r.name,
        description: r.uri,
        detail: r.description,
        resource: r,
      }));
      
      const selected = await vscode.window.showQuickPick(items, {
        placeHolder: 'Select a resource to read',
      });
      
      if (selected) {
        const content = await client.request('resources/read', {
          uri: selected.resource.uri,
        });
        
        // Open in new editor
        const doc = await vscode.workspace.openTextDocument({
          content: content.contents[0].text,
          language: getLanguageId(selected.resource.mimeType),
        });
        
        vscode.window.showTextDocument(doc);
      }
    }
  );
  
  // Execute tool command
  const executeToolCommand = vscode.commands.registerCommand(
    'mcp.executeTool',
    async () => {
      const tools = await client.request('tools/list');
      
      const items = tools.tools.map(t => ({
        label: t.name,
        detail: t.description,
        tool: t,
      }));
      
      const selected = await vscode.window.showQuickPick(items, {
        placeHolder: 'Select a tool to execute',
      });
      
      if (selected) {
        // Get tool arguments
        const argsStr = await vscode.window.showInputBox({
          prompt: `Enter arguments for ${selected.tool.name} (JSON)`,
          placeHolder: '{}',
          value: '{}',
        });
        
        if (argsStr) {
          try {
            const args = JSON.parse(argsStr);
            const result = await client.request('tools/call', {
              name: selected.tool.name,
              arguments: args,
            });
            
            // Show result
            const output = vscode.window.createOutputChannel('MCP Tool Result');
            output.appendLine(`Tool: ${selected.tool.name}`);
            output.appendLine('-'.repeat(50));
            output.appendLine(result.content[0].text);
            output.show();
            
          } catch (error) {
            vscode.window.showErrorMessage(
              `Tool execution failed: ${error.message}`
            );
          }
        }
      }
    }
  );
  
  context.subscriptions.push(listResourcesCommand, executeToolCommand);
}

function getLanguageId(mimeType: string): string {
  const mappings = {
    'text/javascript': 'javascript',
    'text/typescript': 'typescript',
    'text/x-python': 'python',
    'text/markdown': 'markdown',
    'application/json': 'json',
    'text/html': 'html',
    'text/css': 'css',
  };
  return mappings[mimeType] || 'plaintext';
}
```

## Integration Examples

### 1. LangChain Integration

Integrating MCP with LangChain for enhanced AI applications:

```python
# langchain_mcp_integration.py
from langchain.tools import BaseTool
from langchain.agents import initialize_agent, AgentType
from langchain.llms import OpenAI
from mcp import Client
from mcp.client.stdio import StdioClientTransport
import asyncio
import json
from typing import Optional, Type
from pydantic import BaseModel, Field

class MCPToolInput(BaseModel):
    """Input schema for MCP tool"""
    tool_name: str = Field(description="Name of the MCP tool to call")
    arguments: str = Field(description="JSON string of tool arguments")

class MCPTool(BaseTool):
    """LangChain tool that wraps MCP tools"""
    name = "mcp_tool"
    description = "Execute tools from an MCP server"
    args_schema: Type[BaseModel] = MCPToolInput
    mcp_client: Optional[Client] = None
    
    def __init__(self, mcp_client: Client):
        super().__init__()
        self.mcp_client = mcp_client
    
    def _run(self, tool_name: str, arguments: str) -> str:
        """Execute MCP tool synchronously"""
        return asyncio.run(self._arun(tool_name, arguments))
    
    async def _arun(self, tool_name: str, arguments: str) -> str:
        """Execute MCP tool asynchronously"""
        try:
            args = json.loads(arguments)
            result = await self.mcp_client.call_tool(tool_name, args)
            
            # Extract text content
            text_content = []
            for content in result.content:
                if hasattr(content, 'text'):
                    text_content.append(content.text)
            
            return "\n".join(text_content)
            
        except Exception as e:
            return f"Error executing MCP tool: {str(e)}"

class MCPResourceTool(BaseTool):
    """LangChain tool for reading MCP resources"""
    name = "mcp_resource"
    description = "Read resources from an MCP server"
    mcp_client: Optional[Client] = None
    
    def __init__(self, mcp_client: Client):
        super().__init__()
        self.mcp_client = mcp_client
    
    def _run(self, uri: str) -> str:
        """Read MCP resource synchronously"""
        return asyncio.run(self._arun(uri))
    
    async def _arun(self, uri: str) -> str:
        """Read MCP resource asynchronously"""
        try:
            content = await self.mcp_client.read_resource(uri)
            
            # Extract text content
            text_content = []
            for item in content.contents:
                if item.text:
                    text_content.append(item.text)
            
            return "\n".join(text_content)
            
        except Exception as e:
            return f"Error reading MCP resource: {str(e)}"

async def create_mcp_agent():
    """Create a LangChain agent with MCP tools"""
    # Connect to MCP server
    client = Client(name="langchain-mcp", version="1.0.0")
    transport = StdioClientTransport(
        command="python",
        args=["mcp_server.py"]
    )
    await client.connect(transport)
    
    # Get available tools and resources
    tools_list = await client.list_tools()
    resources_list = await client.list_resources()
    
    # Create tool descriptions
    tool_descriptions = []
    for tool in tools_list:
        desc = f"- {tool.name}: {tool.description}"
        if hasattr(tool, 'input_schema'):
            desc += f" (args: {json.dumps(tool.input_schema)})"
        tool_descriptions.append(desc)
    
    resource_descriptions = []
    for resource in resources_list:
        desc = f"- {resource.uri}: {resource.name}"
        resource_descriptions.append(desc)
    
    # Update tool descriptions
    MCPTool.description = f"""Execute tools from MCP server.
Available tools:
{chr(10).join(tool_descriptions)}

To use: provide tool_name and arguments as JSON string."""
    
    MCPResourceTool.description = f"""Read resources from MCP server.
Available resources:
{chr(10).join(resource_descriptions)}

To use: provide the resource URI."""
    
    # Create LangChain tools
    mcp_tool = MCPTool(mcp_client=client)
    mcp_resource = MCPResourceTool(mcp_client=client)
    
    # Initialize LLM and agent
    llm = OpenAI(temperature=0)
    tools = [mcp_tool, mcp_resource]
    
    agent = initialize_agent(
        tools,
        llm,
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True
    )
    
    return agent, client

# Example usage
async def main():
    agent, mcp_client = await create_mcp_agent()
    
    # Example queries
    queries = [
        "What files are available in the resources?",
        "Read the configuration file and summarize its contents",
        "Use the weather tool to get the current weather in London",
        "Create a new file called test.txt with the content 'Hello from LangChain'"
    ]
    
    for query in queries:
        print(f"\nQuery: {query}")
        print("-" * 50)
        response = agent.run(query)
        print(f"Response: {response}")
    
    # Cleanup
    await mcp_client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```

### 2. Jupyter Notebook Integration

MCP integration for Jupyter notebooks:

```python
# mcp_jupyter.py
import asyncio
import json
from IPython.display import display, HTML, JSON
from ipywidgets import widgets, Layout
from mcp import Client
from mcp.client.stdio import StdioClientTransport

class MCPJupyterClient:
    """MCP client for Jupyter notebooks with interactive widgets"""
    
    def __init__(self):
        self.client = None
        self.connected = False
        self.setup_ui()
    
    def setup_ui(self):
        """Create interactive UI widgets"""
        # Connection widgets
        self.server_input = widgets.Text(
            placeholder='python server.py',
            description='Server:',
            layout=Layout(width='400px')
        )
        
        self.connect_button = widgets.Button(
            description='Connect',
            button_style='primary'
        )
        self.connect_button.on_click(self.on_connect_click)
        
        self.status_label = widgets.Label('Not connected')
        
        # Resource browser
        self.resource_dropdown = widgets.Dropdown(
            options=[],
            description='Resource:',
            layout=Layout(width='400px')
        )
        
        self.read_button = widgets.Button(
            description='Read Resource',
            button_style='info',
            disabled=True
        )
        self.read_button.on_click(self.on_read_click)
        
        # Tool executor
        self.tool_dropdown = widgets.Dropdown(
            options=[],
            description='Tool:',
            layout=Layout(width='400px')
        )
        
        self.args_textarea = widgets.Textarea(
            placeholder='{}',
            description='Arguments:',
            layout=Layout(width='400px', height='100px')
        )
        
        self.execute_button = widgets.Button(
            description='Execute Tool',
            button_style='success',
            disabled=True
        )
        self.execute_button.on_click(self.on_execute_click)
        
        # Output area
        self.output = widgets.Output()
        
        # Layout
        self.ui = widgets.VBox([
            widgets.HBox([self.server_input, self.connect_button, self.status_label]),
            widgets.HTML('<hr>'),
            widgets.HTML('<h3>Resources</h3>'),
            widgets.HBox([self.resource_dropdown, self.read_button]),
            widgets.HTML('<h3>Tools</h3>'),
            widgets.VBox([self.tool_dropdown, self.args_textarea, self.execute_button]),
            widgets.HTML('<hr>'),
            self.output
        ])
    
    def display(self):
        """Display the UI"""
        display(self.ui)
    
    def on_connect_click(self, _):
        """Handle connect button click"""
        asyncio.create_task(self.connect())
    
    async def connect(self):
        """Connect to MCP server"""
        server_cmd = self.server_input.value.strip()
        if not server_cmd:
            return
        
        with self.output:
            try:
                self.status_label.value = 'Connecting...'
                
                # Parse command
                parts = server_cmd.split()
                command = parts[0]
                args = parts[1:] if len(parts) > 1 else []
                
                # Create client
                self.client = Client(
                    name="jupyter-mcp",
                    version="1.0.0"
                )
                
                # Connect
                transport = StdioClientTransport(command=command, args=args)
                await self.client.connect(transport)
                
                self.connected = True
                self.status_label.value = f'Connected to {self.client.server_info.name}'
                
                # Load capabilities
                await self.load_capabilities()
                
                # Enable buttons
                self.read_button.disabled = False
                self.execute_button.disabled = False
                
            except Exception as e:
                self.status_label.value = f'Error: {str(e)}'
                self.connected = False
    
    async def load_capabilities(self):
        """Load server capabilities"""
        # Load resources
        resources = await self.client.list_resources()
        self.resource_dropdown.options = [
            (f"{r.name} ({r.uri})", r.uri)
            for r in resources
        ]
        
        # Load tools
        tools = await self.client.list_tools()
        self.tool_dropdown.options = [
            (f"{t.name} - {t.description}", t.name)
            for t in tools
        ]
        
        # Store tool schemas
        self.tool_schemas = {t.name: t for t in tools}
    
    def on_read_click(self, _):
        """Handle read resource button click"""
        asyncio.create_task(self.read_resource())
    
    async def read_resource(self):
        """Read selected resource"""
        if not self.connected:
            return
        
        uri = self.resource_dropdown.value
        if not uri:
            return
        
        with self.output:
            try:
                content = await self.client.read_resource(uri)
                
                # Display content
                for item in content.contents:
                    if item.text:
                        # Try to parse as JSON for pretty display
                        try:
                            data = json.loads(item.text)
                            display(JSON(data))
                        except:
                            print(item.text)
                    elif item.blob:
                        print(f"[Binary data: {len(item.blob)} bytes]")
                        
            except Exception as e:
                print(f"Error reading resource: {e}")
    
    def on_execute_click(self, _):
        """Handle execute tool button click"""
        asyncio.create_task(self.execute_tool())
    
    async def execute_tool(self):
        """Execute selected tool"""
        if not self.connected:
            return
        
        tool_name = self.tool_dropdown.value
        if not tool_name:
            return
        
        with self.output:
            try:
                # Parse arguments
                args_str = self.args_textarea.value.strip() or '{}'
                args = json.loads(args_str)
                
                # Show tool schema if empty args
                if args == {} and tool_name in self.tool_schemas:
                    schema = self.tool_schemas[tool_name]
                    if hasattr(schema, 'input_schema'):
                        print("Tool schema:")
                        display(JSON(schema.input_schema))
                        print("\nExecuting with empty arguments...")
                
                # Execute tool
                result = await self.client.call_tool(tool_name, args)
                
                # Display result
                print(f"\nTool result for '{tool_name}':")
                for content in result.content:
                    if content.text:
                        # Try to parse as JSON for pretty display
                        try:
                            data = json.loads(content.text)
                            display(JSON(data))
                        except:
                            print(content.text)
                    elif hasattr(content, 'data'):
                        # Image data
                        display(HTML(f'<img src="data:{content.mime_type};base64,{content.data}">'))
                
                if result.is_error:
                    print("(Error occurred during execution)")
                    
            except json.JSONDecodeError:
                print("Error: Invalid JSON in arguments")
            except Exception as e:
                print(f"Error executing tool: {e}")
    
    def query(self, question: str):
        """Helper method for quick queries"""
        if not self.connected:
            print("Not connected to MCP server")
            return
        
        # This could be extended to use an LLM to interpret the question
        # and automatically call the right tools/resources
        with self.output:
            print(f"Query: {question}")
            print("(Manual tool/resource selection required)")

# Usage in Jupyter notebook:
# client = MCPJupyterClient()
# client.display()
```

## Advanced Patterns

### 1. Server Composition

Composing multiple MCP servers into a unified interface:

```typescript
// server-composer.ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

interface ServerConfig {
  name: string;
  command: string;
  args: string[];
  prefix: string;
}

class ComposedMCPServer {
  private server: Server;
  private clients: Map<string, Client> = new Map();
  private configs: ServerConfig[];
  
  constructor(configs: ServerConfig[]) {
    this.configs = configs;
    this.server = new Server(
      {
        name: "composed-server",
        version: "1.0.0",
      },
      {
        capabilities: {
          resources: {},
          tools: {},
        },
      }
    );
    
    this.setupHandlers();
  }
  
  async start() {
    // Connect to all upstream servers
    for (const config of this.configs) {
      const client = new Client({
        name: `composer-${config.name}`,
        version: "1.0.0",
      });
      
      const transport = new StdioClientTransport({
        command: config.command,
        args: config.args,
      });
      
      await client.connect(transport);
      this.clients.set(config.name, client);
    }
    
    // Start composed server
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
  }
  
  setupHandlers() {
    // List resources from all servers
    this.server.setRequestHandler("resources/list", async () => {
      const allResources = [];
      
      for (const [name, client] of this.clients) {
        const config = this.configs.find(c => c.name === name)!;
        
        try {
          const response = await client.request("resources/list");
          
          // Prefix resource URIs
          const prefixedResources = response.resources.map(r => ({
            ...r,
            uri: `${config.prefix}:${r.uri}`,
            name: `[${config.name}] ${r.name}`,
          }));
          
          allResources.push(...prefixedResources);
        } catch (error) {
          console.error(`Failed to list resources from ${name}:`, error);
        }
      }
      
      return { resources: allResources };
    });
    
    // Read resources from appropriate server
    this.server.setRequestHandler("resources/read", async (request) => {
      const { uri } = request.params;
      
      // Parse prefixed URI
      const match = uri.match(/^([^:]+):(.+)$/);
      if (!match) {
        throw new Error(`Invalid URI format: ${uri}`);
      }
      
      const [, prefix, actualUri] = match;
      const config = this.configs.find(c => c.prefix === prefix);
      if (!config) {
        throw new Error(`Unknown prefix: ${prefix}`);
      }
      
      const client = this.clients.get(config.name)!;
      const response = await client.request("resources/read", {
        uri: actualUri,
      });
      
      // Rewrite URIs in response
      response.contents = response.contents.map(c => ({
        ...c,
        uri: `${prefix}:${c.uri}`,
      }));
      
      return response;
    });
    
    // List tools from all servers
    this.server.setRequestHandler("tools/list", async () => {
      const allTools = [];
      
      for (const [name, client] of this.clients) {
        const config = this.configs.find(c => c.name === name)!;
        
        try {
          const response = await client.request("tools/list");
          
          // Prefix tool names
          const prefixedTools = response.tools.map(t => ({
            ...t,
            name: `${config.prefix}_${t.name}`,
            description: `[${config.name}] ${t.description}`,
          }));
          
          allTools.push(...prefixedTools);
        } catch (error) {
          console.error(`Failed to list tools from ${name}:`, error);
        }
      }
      
      return { tools: allTools };
    });
    
    // Execute tools on appropriate server
    this.server.setRequestHandler("tools/call", async (request) => {
      const { name, arguments: args } = request.params;
      
      // Parse prefixed tool name
      const match = name.match(/^([^_]+)_(.+)$/);
      if (!match) {
        throw new Error(`Invalid tool name format: ${name}`);
      }
      
      const [, prefix, actualName] = match;
      const config = this.configs.find(c => c.prefix === prefix);
      if (!config) {
        throw new Error(`Unknown prefix: ${prefix}`);
      }
      
      const client = this.clients.get(config.name)!;
      return await client.request("tools/call", {
        name: actualName,
        arguments: args,
      });
    });
  }
}

// Usage
const composer = new ComposedMCPServer([
  {
    name: "filesystem",
    command: "node",
    args: ["./filesystem-server.js"],
    prefix: "fs",
  },
  {
    name: "database",
    command: "python",
    args: ["./database-server.py"],
    prefix: "db",
  },
  {
    name: "api",
    command: "node",
    args: ["./api-server.js"],
    prefix: "api",
  },
]);

composer.start().then(() => {
  console.error("Composed MCP server running");
});
```

### 2. Middleware System

Advanced middleware system for MCP servers:

```typescript
// middleware-system.ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";

type RequestHandler = (request: any) => Promise<any>;
type Middleware = (request: any, next: RequestHandler) => Promise<any>;

class MiddlewareServer extends Server {
  private middlewares: Map<string, Middleware[]> = new Map();
  
  use(method: string | string[], middleware: Middleware) {
    const methods = Array.isArray(method) ? method : [method];
    
    for (const m of methods) {
      if (!this.middlewares.has(m)) {
        this.middlewares.set(m, []);
      }
      this.middlewares.get(m)!.push(middleware);
    }
  }
  
  setRequestHandler(method: string, handler: RequestHandler) {
    const wrappedHandler = async (request: any) => {
      const middlewares = this.middlewares.get(method) || [];
      
      // Build middleware chain
      let index = 0;
      const next = async (req: any): Promise<any> => {
        if (index >= middlewares.length) {
          return handler(req);
        }
        
        const middleware = middlewares[index++];
        return middleware(req, next);
      };
      
      return next(request);
    };
    
    super.setRequestHandler(method, wrappedHandler);
  }
}

// Example middlewares

// Logging middleware
const loggingMiddleware: Middleware = async (request, next) => {
  const start = Date.now();
  console.log(`[${new Date().toISOString()}] ${request.method} - Start`);
  
  try {
    const result = await next(request);
    const duration = Date.now() - start;
    console.log(`[${new Date().toISOString()}] ${request.method} - Success (${duration}ms)`);
    return result;
  } catch (error) {
    const duration = Date.now() - start;
    console.error(`[${new Date().toISOString()}] ${request.method} - Error (${duration}ms):`, error);
    throw error;
  }
};

// Rate limiting middleware
class RateLimiter {
  private requests: Map<string, number[]> = new Map();
  
  constructor(
    private windowMs: number,
    private maxRequests: number
  ) {}
  
  middleware: Middleware = async (request, next) => {
    const key = request.method;
    const now = Date.now();
    
    // Get request timestamps
    const timestamps = this.requests.get(key) || [];
    
    // Remove old timestamps
    const validTimestamps = timestamps.filter(
      t => now - t < this.windowMs
    );
    
    // Check rate limit
    if (validTimestamps.length >= this.maxRequests) {
      throw new Error(
        `Rate limit exceeded for ${key}. Max ${this.maxRequests} requests per ${this.windowMs}ms`
      );
    }
    
    // Add current timestamp
    validTimestamps.push(now);
    this.requests.set(key, validTimestamps);
    
    return next(request);
  };
}

// Caching middleware
class CacheMiddleware {
  private cache: Map<string, { data: any; expires: number }> = new Map();
  
  constructor(private ttlMs: number) {}
  
  middleware: Middleware = async (request, next) => {
    // Only cache read operations
    if (!request.method.includes("read") && !request.method.includes("list")) {
      return next(request);
    }
    
    const key = JSON.stringify({ method: request.method, params: request.params });
    const cached = this.cache.get(key);
    
    if (cached && cached.expires > Date.now()) {
      console.log(`Cache hit for ${request.method}`);
      return cached.data;
    }
    
    const result = await next(request);
    
    this.cache.set(key, {
      data: result,
      expires: Date.now() + this.ttlMs,
    });
    
    return result;
  };
}

// Validation middleware
const validationMiddleware: Middleware = async (request, next) => {
  // Validate resources/read requests
  if (request.method === "resources/read") {
    if (!request.params?.uri) {
      throw new Error("Missing required parameter: uri");
    }
    
    if (typeof request.params.uri !== "string") {
      throw new Error("Parameter 'uri' must be a string");
    }
  }
  
  // Validate tools/call requests
  if (request.method === "tools/call") {
    if (!request.params?.name) {
      throw new Error("Missing required parameter: name");
    }
    
    if (request.params.arguments && typeof request.params.arguments !== "object") {
      throw new Error("Parameter 'arguments' must be an object");
    }
  }
  
  return next(request);
};

// Usage example
const server = new MiddlewareServer(
  {
    name: "middleware-example",
    version: "1.0.0",
  },
  {
    capabilities: {
      resources: {},
      tools: {},
    },
  }
);

// Apply middlewares
server.use(["resources/list", "resources/read", "tools/list", "tools/call"], loggingMiddleware);
server.use(["resources/read", "tools/call"], new RateLimiter(60000, 100).middleware);
server.use(["resources/list", "resources/read"], new CacheMiddleware(30000).middleware);
server.use(["resources/read", "tools/call"], validationMiddleware);

// Define handlers
server.setRequestHandler("resources/list", async () => {
  return {
    resources: [
      {
        uri: "example://resource",
        name: "Example Resource",
        mimeType: "text/plain",
      },
    ],
  };
});

server.setRequestHandler("resources/read", async (request) => {
  return {
    contents: [
      {
        uri: request.params.uri,
        mimeType: "text/plain",
        text: "Resource content with middleware",
      },
    ],
  };
});
```

## Troubleshooting Common Issues

### Connection Issues

1. **Server not starting**
   ```bash
   # Check if port is in use (for HTTP transport)
   lsof -i :3000
   
   # Check process permissions
   ls -la server.js
   chmod +x server.js
   ```

2. **Client can't connect**
   ```typescript
   // Add connection timeout
   const client = new Client({ name: "debug-client", version: "1.0.0" });
   
   try {
     await Promise.race([
       client.connect(transport),
       new Promise((_, reject) => 
         setTimeout(() => reject(new Error("Connection timeout")), 10000)
       )
     ]);
   } catch (error) {
     console.error("Connection failed:", error);
     // Check transport configuration
   }
   ```

### Protocol Issues

1. **Version mismatch**
   ```typescript
   // Handle version negotiation
   server.setRequestHandler("initialize", async (request) => {
     const clientVersion = request.params.protocolVersion;
     const serverVersion = "2025-06-18";
     
     if (!isVersionCompatible(clientVersion, serverVersion)) {
       throw new Error(
         `Protocol version mismatch. Client: ${clientVersion}, Server: ${serverVersion}`
       );
     }
     
     return {
       protocolVersion: serverVersion,
       capabilities: server.capabilities,
       serverInfo: server.info,
     };
   });
   ```

2. **Invalid JSON-RPC messages**
   ```python
   # Add message validation
   def validate_jsonrpc_message(message):
       if "jsonrpc" not in message or message["jsonrpc"] != "2.0":
           raise ValueError("Invalid JSON-RPC version")
       
       if "method" in message:  # Request or notification
           if not isinstance(message["method"], str):
               raise ValueError("Method must be a string")
       
       if "id" in message and message["id"] is None:
           raise ValueError("ID cannot be null")
   ```

### Performance Issues

1. **Slow resource reading**
   ```typescript
   // Implement streaming for large files
   server.setRequestHandler("resources/read", async (request) => {
     const { uri } = request.params;
     const filePath = uri.replace("file://", "");
     
     // Check file size
     const stats = await fs.stat(filePath);
     if (stats.size > 10 * 1024 * 1024) { // 10MB
       // Return reference instead of content
       return {
         contents: [{
           uri,
           mimeType: "application/x-large-file",
           text: JSON.stringify({
             size: stats.size,
             message: "File too large. Use streaming endpoint.",
             streamUri: `stream://${filePath}`
           })
         }]
       };
     }
     
     // Normal file reading for smaller files
     const content = await fs.readFile(filePath, "utf-8");
     return {
       contents: [{ uri, mimeType: "text/plain", text: content }]
     };
   });
   ```

2. **Memory leaks**
   ```python
   # Implement resource cleanup
   class MCPServer:
       def __init__(self):
           self.resources = []
           self.cleanup_interval = 300  # 5 minutes
           self._start_cleanup_task()
       
       def _start_cleanup_task(self):
           async def cleanup():
               while True:
                   await asyncio.sleep(self.cleanup_interval)
                   self._cleanup_expired_resources()
           
           asyncio.create_task(cleanup())
       
       def _cleanup_expired_resources(self):
           # Remove expired cached resources
           now = time.time()
           self.resources = [
               r for r in self.resources
               if not hasattr(r, 'expires') or r.expires > now
           ]
   ```

### Debugging Tips

1. **Enable verbose logging**
   ```typescript
   // Set environment variable
   process.env.MCP_LOG_LEVEL = "debug";
   
   // Or in code
   server.setLogLevel("debug");
   client.setLogLevel("debug");
   ```

2. **Protocol tracing**
   ```python
   # Log all protocol messages
   class DebugTransport(StdioServerTransport):
       async def send(self, message):
           print(f">>> {json.dumps(message, indent=2)}")
           await super().send(message)
       
       async def receive(self):
           message = await super().receive()
           print(f"<<< {json.dumps(message, indent=2)}")
           return message
   ```

3. **Health checks**
   ```typescript
   // Add health endpoint
   server.setRequestHandler("health", async () => {
     return {
       status: "healthy",
       uptime: process.uptime(),
       memory: process.memoryUsage(),
       version: server.version,
     };
   });
   ```

## Next Steps

- **Resources**: Additional learning resources and references
- **Protocol Specification**: Deep dive into protocol details
- **Security**: Best practices for secure MCP implementations