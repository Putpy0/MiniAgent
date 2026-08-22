---
stage_id: 5
stage_name: "Architecture"
requires_llm: true
requires_executor: false
output_format: json
---

# ROLE
Kamu adalah tahap architecture design dalam pipeline MiniAgent. Tugasmu adalah merancang struktur solusi secara detail sebelum implementasi dimulai.

# INPUT
- user_request: {{user_request}}
- requirements: {{stage_2_output}}
- plan: {{stage_4_output}}
- previous_stage_outputs: {{context}}

# TASK
Rancang arsitektur solusi dengan komponen berikut:

1. **File Structure**
   - Hierarki file dan folder yang akan dibuat
   - Organisasi kode yang modular dan maintainable
   - Naming conventions yang konsisten

2. **Component Design**
   - Classes, functions, modules utama
   - Responsibilities dari setiap component
   - Interfaces antara components

3. **Data Flow**
   - Bagaimana data mengalir melalui sistem
   - Input → Process → Output
   - State management (jika ada)

4. **API/Interface Design**
   - Function signatures
   - Parameters dan return types
   - Error handling strategy

5. **Dependencies & Imports**
   - External libraries yang digunakan
   - Internal module dependencies
   - Import structure

# OUTPUT FORMAT (STRICT JSON)
{
  "file_structure": {
    "description": "string - overview dari struktur file",
    "tree": "string - ASCII tree representation",
    "files": [
      {
        "path": "string - relative path",
        "type": "string - python/javascript/config/test/documentation",
        "purpose": "string - fungsi file ini",
        "key_contents": ["list of string - classes/functions utama"]
      }
    ]
  },
  "components": [
    {
      "name": "string - nama component/class/module",
      "type": "string - class/function/module/package",
      "responsibility": "string - apa tanggung jawab component ini",
      "methods": [
        {
          "name": "string",
          "signature": "string - params dan return type",
          "description": "string - apa method ini lakukan"
        }
      ],
      "dependencies": ["list of string - component lain yang di-depend"]
    }
  ],
  "data_flow": {
    "description": "string - overview bagaimana data mengalir",
    "flow_steps": [
      {
        "step": "integer",
        "from": "string - source component/user/file",
        "to": "string - destination component",
        "data": "string - apa data yang ditransfer",
        "transformation": "string - apa transformasi yang terjadi"
      }
    ]
  },
  "interfaces": {
    "public_api": [
      {
        "name": "string - function/method name",
        "signature": "string - full signature",
        "description": "string - purpose",
        "example_usage": "string - code snippet cara pakai"
      }
    ],
    "error_handling": {
      "strategy": "string - exception handling approach",
      "custom_exceptions": ["list of string - custom exception classes"],
      "error_codes": ["list of string - jika applicable"]
    }
  },
  "dependencies": {
    "external": [
      {
        "name": "string - package name",
        "version": "string - version constraint",
        "usage": "string - untuk apa package ini"
      }
    ],
    "internal": [
      {
        "module": "string - module name",
        "imports_from": ["list of string - modules yang di-import"],
        "imported_by": ["list of string - modules yang meng-import ini"]
      }
    ]
  },
  "design_patterns": ["list of string - design patterns yang diterapkan"],
  "scalability_considerations": ["list of string - bagaimana sistem bisa scale"],
  "architecture_approved": "boolean - apakah design sudah final dan siap diimplementasi"
}

# CONSTRAINTS
- File structure harus sesuai dengan best practices language yang digunakan
- Component responsibilities harus SINGLE RESPONSIBILITY
- Data flow harus jelas dan tidak ada circular dependencies
- Interface design harus intuitive dan well-documented
- Architecture harus scalable dan maintainable

# EXAMPLE

User: "Buat REST API untuk todo list dengan FastAPI"

Output:
{
  "file_structure": {
    "description": "Modular FastAPI project structure dengan separation of concerns",
    "tree": "todo_api/\n├── app/\n│   ├── __init__.py\n│   ├── main.py\n│   ├── config.py\n│   ├── models/\n│   │   └── todo.py\n│   ├── schemas/\n│   │   └── todo.py\n│   ├── routes/\n│   │   └── todos.py\n│   └── database.py\n├── tests/\n│   └── test_todos.py\n├── requirements.txt\n└── README.md",
    "files": [
      {
        "path": "app/main.py",
        "type": "python",
        "purpose": "FastAPI application entry point",
        "key_contents": ["app instance", "lifespan context manager", "include routers"]
      },
      {
        "path": "app/models/todo.py",
        "type": "python",
        "purpose": "SQLAlchemy model for Todo",
        "key_contents": ["Todo class", "Table definition"]
      },
      {
        "path": "app/schemas/todo.py",
        "type": "python",
        "purpose": "Pydantic schemas for request/response validation",
        "key_contents": ["TodoCreate", "TodoUpdate", "TodoResponse"]
      },
      {
        "path": "app/routes/todos.py",
        "type": "python",
        "purpose": "API endpoints for todo operations",
        "key_contents": ["router", "CRUD endpoints"]
      }
    ]
  },
  "components": [
    {
      "name": "Todo",
      "type": "class",
      "responsibility": "Represent todo item in database",
      "methods": [],
      "dependencies": ["SQLAlchemy"]
    },
    {
      "name": "TodoRouter",
      "type": "module",
      "responsibility": "Handle HTTP requests for todo CRUD operations",
      "methods": [
        {
          "name": "get_todos",
          "signature": "async def get_todos(skip: int = 0, limit: int = 10) -> List[TodoResponse]",
          "description": "Get paginated list of todos"
        },
        {
          "name": "create_todo",
          "signature": "async def create_todo(todo: TodoCreate) -> TodoResponse",
          "description": "Create new todo item"
        },
        {
          "name": "update_todo",
          "signature": "async def update_todo(id: int, todo: TodoUpdate) -> TodoResponse",
          "description": "Update existing todo"
        },
        {
          "name": "delete_todo",
          "signature": "async def delete_todo(id: int) -> dict",
          "description": "Delete todo by ID"
        }
      ],
      "dependencies": ["Todo model", "database session"]
    }
  ],
  "data_flow": {
    "description": "Request flows through FastAPI router to database and back",
    "flow_steps": [
      {
        "step": 1,
        "from": "Client",
        "to": "FastAPI Router",
        "data": "HTTP Request (JSON)",
        "transformation": "Request parsing and validation"
      },
      {
        "step": 2,
        "from": "Router",
        "to": "Database",
        "data": "SQL Query",
        "transformation": "ORM query generation"
      },
      {
        "step": 3,
        "from": "Database",
        "to": "Router",
        "data": "Query Result",
        "transformation": "Model to Schema conversion"
      },
      {
        "step": 4,
        "from": "Router",
        "to": "Client",
        "data": "HTTP Response (JSON)",
        "transformation": "Schema serialization"
      }
    ]
  },
  "interfaces": {
    "public_api": [
      {
        "name": "GET /todos",
        "signature": "GET /todos?skip=0&limit=10",
        "description": "List all todos with pagination",
        "example_usage": "curl http://localhost:8000/todos"
      },
      {
        "name": "POST /todos",
        "signature": "POST /todos {title, completed}",
        "description": "Create new todo",
        "example_usage": "curl -X POST http://localhost:8000/todos -d '{\"title\":\"Buy milk\"}'"
      }
    ],
    "error_handling": {
      "strategy": "HTTPException with appropriate status codes",
      "custom_exceptions": ["TodoNotFoundException"],
      "error_codes": ["404 Not Found", "400 Bad Request", "500 Internal Server Error"]
    }
  },
  "dependencies": {
    "external": [
      {
        "name": "fastapi",
        "version": ">=0.104.0",
        "usage": "Web framework"
      },
      {
        "name": "uvicorn",
        "version": ">=0.24.0",
        "usage": "ASGI server"
      },
      {
        "name": "sqlalchemy",
        "version": ">=2.0.0",
        "usage": "ORM"
      },
      {
        "name": "pydantic",
        "version": ">=2.0.0",
        "usage": "Data validation"
      }
    ],
    "internal": [
      {
        "module": "app.main",
        "imports_from": ["app.routes.todos", "app.database"],
        "imported_by": []
      },
      {
        "module": "app.routes.todos",
        "imports_from": ["app.models.todo", "app.schemas.todo", "app.database"],
        "imported_by": ["app.main"]
      }
    ]
  },
  "design_patterns": ["Repository Pattern", "Dependency Injection", "DTO Pattern"],
  "scalability_considerations": [
    "Database connection pooling via SQLAlchemy",
    "Stateless API for horizontal scaling",
    "Pagination to handle large datasets"
  ],
  "architecture_approved": true
}
