import { requestDreaminaWebImageGeneration } from "./dreamina_web_cdp.mjs";

function normalizeText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function parseArgs(argv = []) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const current = normalizeText(argv[index]);
    if (!current.startsWith("--")) {
      continue;
    }
    const key = current.slice(2);
    const next = argv[index + 1];
    if (typeof next === "string" && !next.startsWith("--")) {
      args[key] = next;
      index += 1;
      continue;
    }
    args[key] = "true";
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const prompt = normalizeText(args.prompt);
  if (!prompt) {
    throw new Error("dreamina_smoke_prompt_missing");
  }

  const referenceImage = normalizeText(args.reference);
  const requestSpec = {
    prompt,
    prompt_base64: Buffer.from(prompt, "utf8").toString("base64")
  };

  if (referenceImage) {
    requestSpec.reference_images = [
      {
        path: referenceImage,
        alias: normalizeText(args.alias) || "reference_image"
      }
    ];
  }
  if (normalizeText(args.model)) {
    requestSpec.model = normalizeText(args.model);
    requestSpec.modelVersion = normalizeText(args.model);
  }
  if (normalizeText(args.ratio)) {
    requestSpec.ratio = normalizeText(args.ratio);
  }

  const config = {};
  if (normalizeText(args.template)) {
    config.templatePath = normalizeText(args.template);
  }
  if (normalizeText(args.profile)) {
    config.cdpUserDataDir = normalizeText(args.profile);
  }
  if (normalizeText(args.headlessProfile)) {
    config.cdpHeadlessUserDataDir = normalizeText(args.headlessProfile);
  }
  if (normalizeText(args.cdpBaseUrl)) {
    config.cdpBaseUrl = normalizeText(args.cdpBaseUrl);
    config.cdpCookieSourceBaseUrl = normalizeText(args.cdpBaseUrl);
  }
  if (normalizeText(args.pageUrl)) {
    config.cdpTargetPageUrl = normalizeText(args.pageUrl);
  }
  if (normalizeText(args.captureOnly).toLowerCase() === "true") {
    config.captureOnly = true;
  }

  const result = await requestDreaminaWebImageGeneration({
    env: process.env,
    config,
    requestSpec
  });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

main().catch((error) => {
  const message = normalizeText(error?.stack) || normalizeText(error?.message) || "dreamina_smoke_failed";
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
});
