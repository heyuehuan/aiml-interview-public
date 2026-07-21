"""
UniLLM Proxy Server

A minimal OpenAI-compatible API proxy for Vertex AI Gemini.
"""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import yaml
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from unillm import __version__
from unillm._logging import verbose_proxy_logger, set_verbose
from unillm.proxy import limits, transcript
from unillm.proxy.auth import user_api_key_auth
from unillm.types import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    CompletionRequest,
    CompletionResponse,
    ModelInfo,
    ModelListResponse,
    UserAPIKeyAuth,
)
from unillm.llm.vertex_ai import VertexAIHandler
# CMEK/KMS path needs the heavy `vertexai` SDK and is unused here (owner decision:
# master-key model, no CMEK). Keep it optional so plain Vertex works without that dep.
try:
    from unillm.llm.vertex_ai_kms import VertexAIKMSHandler
except ImportError:  # pragma: no cover - only hit when a vertex-ai-kms model is configured
    VertexAIKMSHandler = None


# Model type constants
MODEL_TYPE_VERTEX_AI = "vertex-ai"
MODEL_TYPE_VERTEX_AI_KMS = "vertex-ai-kms"

# Global configuration
model_list: List[Dict[str, Any]] = []
general_settings: Dict[str, Any] = {}
vertex_handlers: Dict[str, VertexAIHandler] = {}


class ProxyConfig:
    """Proxy configuration manager"""
  
    def __init__(self):
        self.model_list: List[Dict[str, Any]] = []
        self.general_settings: Dict[str, Any] = {}
  
    async def load_config(self, config_file_path: str) -> None:
        """Load configuration from YAML file"""
        global model_list, general_settings, vertex_handlers
      
        if not os.path.exists(config_file_path):
            verbose_proxy_logger.warning(f"Config file not found: {config_file_path}")
            return
      
        with open(config_file_path, "r") as f:
            config = yaml.safe_load(f)
      
        # Load model list
        self.model_list = config.get("model_list", [])
        model_list = self.model_list
      
        # Load general settings
        self.general_settings = config.get("general_settings", {})
        general_settings = self.general_settings
      
        # Initialize handlers for each model
        for model_config in self.model_list:
            model_name = model_config.get("model_name")
            params = model_config.get("litellm_params", {})
          
            # For backward compatibility with litellm config
            unillm_params = model_config.get("unillm_params", params)
          
            project = unillm_params.get("project")
            location = unillm_params.get("location", "us-central1")
            model_type = unillm_params.get("model_type", MODEL_TYPE_VERTEX_AI)
          
            # Route to appropriate handler based on model_type
            if model_type == MODEL_TYPE_VERTEX_AI_KMS:
                kms_key_name = unillm_params.get("kms_key_name")
                vertex_handlers[model_name] = VertexAIKMSHandler(
                    project=project,
                    location=location,
                    kms_key_name=kms_key_name,
                )
                verbose_proxy_logger.info(
                    f"Initialized KMS handler for model '{model_name}' with KMS key"
                )
            else:
                # Default: vertex-ai
                vertex_handlers[model_name] = VertexAIHandler(
                    project=project,
                    location=location,
                )
      
        verbose_proxy_logger.info(f"Loaded {len(self.model_list)} models from config")
  
    def get_model_config(self, model_name: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific model"""
        for model_config in self.model_list:
            if model_config.get("model_name") == model_name:
                return model_config
        return None


# Global proxy config instance
proxy_config = ProxyConfig()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    verbose_proxy_logger.info(f"UniLLM Proxy v{__version__} starting...")
  
    # Load config if provided
    config_path = os.getenv("UNILLM_CONFIG", "")
    if config_path and os.path.exists(config_path):
        await proxy_config.load_config(config_path)
  
    yield
  
    # Shutdown
    verbose_proxy_logger.info("UniLLM Proxy shutting down...")
    # Close all handlers
    for handler in vertex_handlers.values():
        await handler.close()


# the interactive API docs expose the full schema of an SA-backed proxy that sits
# on the candidate net. Off by default; opt in with UNILLM_ENABLE_DOCS=1 for local dev.
_enable_docs = os.getenv("UNILLM_ENABLE_DOCS", "0") == "1"

# Create FastAPI app
app = FastAPI(
    title="UniLLM Proxy",
    description="A minimal OpenAI-compatible API proxy for Vertex AI Gemini",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs" if _enable_docs else None,
    redoc_url="/redoc" if _enable_docs else None,
    openapi_url="/openapi.json" if _enable_docs else None,
)

# CORS: the proxy is called server-side (portal) and via the workspace loopback
# forwarder with a Bearer key — never with browser cookies — so credentialed CORS is
# unnecessary and unsafe paired with a wildcard origin. Default to no cross-origin
# allowance; UNILLM_CORS_ORIGINS (comma-separated) opts specific origins back in.
_cors_origins = [o.strip() for o in os.getenv("UNILLM_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": __version__}


@app.get("/")
async def root():
    """Root endpoint - redirects to docs when they're enabled, else a bare status."""
    if _enable_docs:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/docs")
    return {"service": "unillm", "version": __version__}


# Model endpoints
@app.get("/v1/models", dependencies=[Depends(user_api_key_auth)])
@app.get("/models", dependencies=[Depends(user_api_key_auth)])
async def list_models(
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
) -> ModelListResponse:
    """
    List available models.
  
    Returns a list of models configured in the proxy.
    """
    models = []
    for model_config in model_list:
        model_name = model_config.get("model_name", "")
        models.append(ModelInfo(
            id=model_name,
            object="model",
            created=int(time.time()),
            owned_by="vertex_ai",
        ))
  
    return ModelListResponse(object="list", data=models)


@app.get("/v1/models/{model_id}", dependencies=[Depends(user_api_key_auth)])
@app.get("/models/{model_id}", dependencies=[Depends(user_api_key_auth)])
async def get_model(
    model_id: str,
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
) -> ModelInfo:
    """
    Get information about a specific model.
    """
    # Check if model exists
    model_config = proxy_config.get_model_config(model_id)
    if model_config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model_id}' not found",
        )
  
    return ModelInfo(
        id=model_id,
        object="model",
        created=int(time.time()),
        owned_by="vertex_ai",
    )


async def _read_request_body(request: Request) -> Dict[str, Any]:
    """Read and parse the request body"""
    body = await request.body()
    try:
        return json.loads(body) if body else {}
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {str(e)}",
        )


def _get_handler_for_model(model_name: str) -> VertexAIHandler:
    """Get the handler for an allowlisted model; 400 on anything else.

    The config's model_list IS the model gate: without this check a
    caller could reach any publishers/google/models/* in the SA's project by naming
    it. No configured models ⇒ every request is rejected (fail closed)."""
    if model_name in vertex_handlers:
        handler = vertex_handlers[model_name]
        verbose_proxy_logger.debug(f"Using cached handler for model '{model_name}': {type(handler).__name__}")
        return handler

    # Try to find a matching model configuration
    model_config = proxy_config.get_model_config(model_name)
    if model_config:
        params = model_config.get("litellm_params", model_config.get("unillm_params", {}))
        model_type = params.get("model_type", MODEL_TYPE_VERTEX_AI)
        verbose_proxy_logger.debug(f"Model '{model_name}' has model_type: {model_type}")

        # Route to appropriate handler based on model_type
        if model_type == MODEL_TYPE_VERTEX_AI_KMS:
            return VertexAIKMSHandler(
                project=params.get("project"),
                location=params.get("location", "us-central1"),
                kms_key_name=params.get("kms_key_name"),
            )
        else:
            return VertexAIHandler(
                project=params.get("project"),
                location=params.get("location", "us-central1"),
            )

    # Not in the allowlist: reject rather than fall through to a default handler
    # that would forward an arbitrary model name upstream.
    verbose_proxy_logger.warning(f"Rejected request for non-allowlisted model '{model_name}'")
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Model '{model_name}' is not available. Use /v1/models to list the served models.",
    )


def _get_actual_model_name(model_name: str) -> str:
    """Get the actual model name to use with Vertex AI"""
    model_config = proxy_config.get_model_config(model_name)
    if model_config:
        params = model_config.get("litellm_params", model_config.get("unillm_params", {}))
        actual_model = params.get("model", model_name)
        # Remove vertex_ai/ prefix if present
        if actual_model.startswith("vertex_ai/"):
            actual_model = actual_model[len("vertex_ai/"):]
        return actual_model
    return model_name


def _get_model_params(model_name: str) -> Dict[str, Any]:
    """Get model-specific parameters"""
    model_config = proxy_config.get_model_config(model_name)
    if model_config:
        return model_config.get("litellm_params", model_config.get("unillm_params", {}))
    return {}


def _enforce_rate_limit(user_api_key_dict: UserAPIKeyAuth) -> None:
    """Reject with 429 when this key is over its per-minute budget."""
    if not limits.check_rate_limit(user_api_key_dict.api_key):
        verbose_proxy_logger.warning("Rate limit exceeded for a key")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Slow down and retry shortly.",
            headers={"Retry-After": "60"},
        )


# Chat completions endpoint
@app.post("/v1/chat/completions", dependencies=[Depends(user_api_key_auth)])
@app.post("/chat/completions", dependencies=[Depends(user_api_key_auth)])
async def chat_completions(
    request_body: ChatCompletionRequest,
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    Create a chat completion.
  
    Follows the OpenAI Chat Completions API specification.
    https://platform.openai.com/docs/api-reference/chat/create
    """
    _enforce_rate_limit(user_api_key_dict)
    # Extract parameters from request body
    model = request_body.model
    messages = [msg.model_dump(exclude_none=True) for msg in request_body.messages]
    stream = request_body.stream or False
    temperature = request_body.temperature
    top_p = request_body.top_p
    max_tokens = limits.cap_output_tokens(request_body.max_tokens)  # hard ceiling
    stop = request_body.stop
  
    # Get handler and model config
    handler = _get_handler_for_model(model)
    actual_model = _get_actual_model_name(model)
    model_params = _get_model_params(model)
  
    verbose_proxy_logger.debug(f"Chat completion request for model: {model} -> {actual_model}")

    started = time.monotonic()  # transcript: latency of the call we are about to audit
    try:
        # Build kwargs for handler - include kms_key_name if present (for vertex-ai-kms)
        handler_kwargs = {
            "model": actual_model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stop": stop,
            "stream": stream,
            "project": model_params.get("project"),
            "location": model_params.get("location"),
        }
      
        # Add kms_key_name if present (for vertex-ai-kms handler)
        if model_params.get("kms_key_name"):
            handler_kwargs["kms_key_name"] = model_params.get("kms_key_name")
      
        response = await handler.chat_completion(**handler_kwargs)

        if stream:
            # Tee the stream into the transcript: the candidate gets every chunk
            # untouched, and the audit trail still records what was generated.
            return StreamingResponse(
                transcript.tee_stream(response, endpoint="chat.completions", model=model,
                                      messages=messages, started=started),
                media_type="text/event-stream",
            )
        else:
            # Update model name in response to match request
            response.model = model
            transcript.record(
                endpoint="chat.completions", model=model, messages=messages,
                response_text=transcript.text_of(response),
                usage=transcript.usage_of(response),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            return response

    except Exception as e:
        verbose_proxy_logger.exception(f"Error in chat completion: {e}")
        transcript.record(
            endpoint="chat.completions", model=model, messages=messages, error=e,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# Text completions endpoint
@app.post("/v1/completions", dependencies=[Depends(user_api_key_auth)])
@app.post("/completions", dependencies=[Depends(user_api_key_auth)])
async def completions(
    request_body: CompletionRequest,
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    Create a text completion.
  
    Follows the OpenAI Completions API specification.
    https://platform.openai.com/docs/api-reference/completions/create
    """
    _enforce_rate_limit(user_api_key_dict)
    # Extract parameters from request body
    model = request_body.model
    prompt = request_body.prompt
    stream = request_body.stream or False
    temperature = request_body.temperature
    top_p = request_body.top_p
    max_tokens = limits.cap_output_tokens(request_body.max_tokens)  # hard ceiling
    stop = request_body.stop
  
    # Get handler and model config
    handler = _get_handler_for_model(model)
    actual_model = _get_actual_model_name(model)
    model_params = _get_model_params(model)
  
    verbose_proxy_logger.debug(f"Text completion request for model: {model} -> {actual_model}")

    started = time.monotonic()  # transcript: latency of the call we are about to audit
    try:
        # Build kwargs for handler - include kms_key_name if present (for vertex-ai-kms)
        handler_kwargs = {
            "model": actual_model,
            "prompt": prompt,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stop": stop,
            "stream": stream,
            "project": model_params.get("project"),
            "location": model_params.get("location"),
        }
      
        # Add kms_key_name if present (for vertex-ai-kms handler)
        if model_params.get("kms_key_name"):
            handler_kwargs["kms_key_name"] = model_params.get("kms_key_name")
      
        response = await handler.text_completion(**handler_kwargs)

        if stream:
            return StreamingResponse(
                transcript.tee_stream(response, endpoint="completions", model=model,
                                      prompt=prompt, started=started),
                media_type="text/event-stream",
            )
        else:
            # Update model name in response to match request
            response.model = model
            transcript.record(
                endpoint="completions", model=model, prompt=prompt,
                response_text=transcript.text_of(response),
                usage=transcript.usage_of(response),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            return response

    except Exception as e:
        verbose_proxy_logger.exception(f"Error in text completion: {e}")
        transcript.record(
            endpoint="completions", model=model, prompt=prompt, error=e,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# Function to run the server
def run_server(
    host: str = "0.0.0.0",
    port: int = 4000,
    config: Optional[str] = None,
    debug: bool = False,
):
    """Run the UniLLM proxy server"""
    import uvicorn
  
    if debug:
        set_verbose(True)
  
    if config:
        os.environ["UNILLM_CONFIG"] = config
  
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="debug" if debug else "info",
    )
