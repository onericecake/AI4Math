// One Pi request per process. The access token enters only through stdin.
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

let token = "";
try {
  const request = JSON.parse(await readFile(0, "utf8"));
  token = request.token;
  const entry = (file) => pathToFileURL(join(request.package_path, "dist", file)).href;
  const { createModels, envApiKeyAuth } = await import(entry("index.js"));
  const { openaiCodexProvider } = await import(entry("providers/openai-codex.js"));
  const models = createModels();
  models.setProvider({ ...openaiCodexProvider(), auth: { apiKey: envApiKeyAuth("Codex gateway", []) } });
  const model = models.getModel("openai-codex", request.model);
  if (!model) throw new Error(`Unknown Pi Codex model: ${request.model}`);
  const messages = [
    { role: "user", content: "Exact problem and completion criteria:\n" + request.problem, timestamp: Date.now() },
    ...request.context.map((part) => ({ role: "user", content: JSON.stringify(part), timestamp: Date.now() })),
  ];
  const context = {
    systemPrompt: request.instructions + "\nSubmit exactly one result through the submit_result tool.",
    messages,
    tools: [{
      name: "submit_result",
      description: "Submit the complete structured result for this role.",
      parameters: request.schema,
      constrainedSampling: { type: "json_schema", strict: "prefer" },
    }],
  };
  const response = await models.complete(model, context, {
    apiKey: token,
    reasoningEffort: request.effort,
    // Advisory for the installed Codex provider: its request builder omits this field.
    maxTokens: request.max_output_tokens,
    ...(request.timeout_ms > 0 ? { timeoutMs: request.timeout_ms } : {}),
    transport: "sse",
    toolChoice: "required",
    maxRetries: 0,
    sessionId: request.session_id,
    cacheRetention: "short",
  });
  if (response.stopReason !== "toolUse") throw new Error(`Pi ended with ${response.stopReason}: ${response.errorMessage ?? "no structured result"}`);
  const calls = response.content.filter((block) => block.type === "toolCall" && block.name === "submit_result");
  if (calls.length !== 1) throw new Error(`Expected one submit_result call; got ${calls.length}`);
  process.stdout.write(JSON.stringify({ result: calls[0].arguments, usage: response.usageReported ? response.usage : null }));
} catch (error) {
  const message = String(error?.message ?? error);
  const detail = token ? message.replaceAll(token, "[redacted]") : message;
  process.stderr.write(detail + "\n");
  process.exitCode = 1;
}
