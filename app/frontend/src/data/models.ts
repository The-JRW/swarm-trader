import { api } from '@/services/api';

export interface LanguageModel {
  display_name: string;
  model_name: string;
  provider:
    | "Anthropic"
    | "DeepSeek"
    | "Google"
    | "Groq"
    | "OpenAI"
    | "OpenRouter"
    | "GigaChat"
    | "Azure OpenAI"
    | "xAI"
    | "Ollama"
    | string;
}

// Cache for models to avoid repeated API calls
let languageModels: LanguageModel[] | null = null;

/**
 * Get the list of models from the backend API
 * Uses caching to avoid repeated API calls
 */
export const getModels = async (): Promise<LanguageModel[]> => {
  if (languageModels) {
    return languageModels;
  }
  
  try {
    languageModels = await api.getLanguageModels();
    return languageModels;
  } catch (error) {
    console.error('Failed to fetch models:', error);
    throw error; // Let the calling component handle the error
  }
};

/**
 * Prefer OpenRouter as the default model when present in the catalog.
 * Falls back to gpt-4.1, then first model.
 */
export const getDefaultModel = async (): Promise<LanguageModel | null> => {
  try {
    const models = await getModels();
    const openRouterPreferred = models.find(
      (model) =>
        model.provider === "OpenRouter" &&
        model.model_name === "openai/gpt-4o-mini"
    );
    if (openRouterPreferred) return openRouterPreferred;

    const anyOpenRouter = models.find((model) => model.provider === "OpenRouter");
    if (anyOpenRouter) return anyOpenRouter;

    return models.find((model) => model.model_name === "gpt-4.1") || models[0] || null;
  } catch (error) {
    console.error('Failed to get default model:', error);
    return null;
  }
};
