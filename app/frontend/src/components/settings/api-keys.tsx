import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { apiKeysService } from '@/services/api-keys-api';
import { Eye, EyeOff, Key, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

interface ApiKeyDef {
  key: string;
  label: string;
  description: string;
  url: string;
  placeholder: string;
}

const MASKED_PLACEHOLDER = '••••••••••••••••';

const FINANCIAL_API_KEYS: ApiKeyDef[] = [
  {
    key: 'TIINGO_API_KEY',
    label: 'Tiingo API',
    description: 'Secondary market data (Alpaca SIP is primary via server env)',
    url: 'https://www.tiingo.com/',
    placeholder: 'your-tiingo-api-key'
  },
  {
    key: 'FINANCIAL_DATASETS_API_KEY',
    label: 'Financial Datasets API',
    description: 'Legacy financial data API (optional; free yfinance/SEC fallbacks exist)',
    url: 'https://financialdatasets.ai/',
    placeholder: 'your-financial-datasets-api-key'
  }
];

const LLM_API_KEYS: ApiKeyDef[] = [
  {
    key: 'OPENROUTER_API_KEY',
    label: 'OpenRouter API',
    description: 'Primary LLM provider (gpt-4o-mini and other OpenRouter models)',
    url: 'https://openrouter.ai/',
    placeholder: 'your-openrouter-api-key'
  },
  {
    key: 'ANTHROPIC_API_KEY',
    label: 'Anthropic API',
    description: 'For Claude models (claude-4-sonnet, claude-4.1-opus, etc.)',
    url: 'https://anthropic.com/',
    placeholder: 'your-anthropic-api-key'
  },
  {
    key: 'DEEPSEEK_API_KEY',
    label: 'DeepSeek API',
    description: 'For DeepSeek models (deepseek-chat, deepseek-reasoner, etc.)',
    url: 'https://deepseek.com/',
    placeholder: 'your-deepseek-api-key'
  },
  {
    key: 'GROQ_API_KEY',
    label: 'Groq API',
    description: 'For Groq-hosted models (deepseek, llama3, etc.)',
    url: 'https://groq.com/',
    placeholder: 'your-groq-api-key'
  },
  {
    key: 'GOOGLE_API_KEY',
    label: 'Google API',
    description: 'For Gemini models (gemini-2.5-flash, gemini-2.5-pro)',
    url: 'https://ai.dev/',
    placeholder: 'your-google-api-key'
  },
  {
    key: 'OPENAI_API_KEY',
    label: 'OpenAI API',
    description: 'For OpenAI models (gpt-4o, gpt-4o-mini, etc.)',
    url: 'https://platform.openai.com/',
    placeholder: 'your-openai-api-key'
  },
  {
    key: 'GIGACHAT_API_KEY',
    label: 'GigaChat API',
    description: 'For GigaChat models (GigaChat-2-Max, etc.)',
    url: 'https://github.com/ai-forever/gigachat',
    placeholder: 'your-gigachat-api-key'
  }
];

export function ApiKeysSettings() {
  /** Full key values — only populated after eye-reveal or local edit */
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  /** Providers known to have a key configured (from summary has_key) */
  const [configured, setConfigured] = useState<Record<string, boolean>>({});
  const [visibleKeys, setVisibleKeys] = useState<Record<string, boolean>>({});
  const [revealing, setRevealing] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadApiKeys = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      // Summaries only — do not fetch full secrets on load
      const apiKeysSummary = await apiKeysService.getAllApiKeys();
      const configuredMap: Record<string, boolean> = {};
      for (const summary of apiKeysSummary) {
        configuredMap[summary.provider] = Boolean(summary.has_key);
      }
      setConfigured(configuredMap);
      // Clear any previously revealed values after a refresh
      setApiKeys({});
      setVisibleKeys({});
    } catch (err) {
      console.error('Failed to load API keys:', err);
      setError('Could not load API key status. You can still enter keys below, or retry.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadApiKeys();
  }, [loadApiKeys]);

  const handleKeyChange = async (key: string, value: string) => {
    setApiKeys(prev => ({
      ...prev,
      [key]: value
    }));

    try {
      if (value.trim()) {
        await apiKeysService.createOrUpdateApiKey({
          provider: key,
          key_value: value.trim(),
          is_active: true
        });
        setConfigured(prev => ({ ...prev, [key]: true }));
        setError(null);
      } else {
        try {
          await apiKeysService.deleteApiKey(key);
        } catch {
          // Key might not exist
        }
        setConfigured(prev => {
          const next = { ...prev };
          delete next[key];
          return next;
        });
      }
    } catch (err) {
      console.error(`Failed to save API key ${key}:`, err);
      setError(`Failed to save ${key}. Please try again.`);
    }
  };

  const toggleKeyVisibility = async (key: string) => {
    const willShow = !visibleKeys[key];

    if (willShow && configured[key] && !apiKeys[key]) {
      // Fetch full key only on reveal
      try {
        setRevealing(prev => ({ ...prev, [key]: true }));
        const fullKey = await apiKeysService.getApiKey(key);
        setApiKeys(prev => ({ ...prev, [key]: fullKey.key_value }));
      } catch (err) {
        console.error(`Failed to reveal API key ${key}:`, err);
        setError(`Could not reveal ${key}. Retry or re-enter the key.`);
        return;
      } finally {
        setRevealing(prev => {
          const next = { ...prev };
          delete next[key];
          return next;
        });
      }
    }

    setVisibleKeys(prev => ({
      ...prev,
      [key]: willShow
    }));
  };

  const clearKey = async (key: string) => {
    try {
      await apiKeysService.deleteApiKey(key);
      setApiKeys(prev => {
        const newKeys = { ...prev };
        delete newKeys[key];
        return newKeys;
      });
      setConfigured(prev => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      setVisibleKeys(prev => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    } catch (err) {
      console.error(`Failed to delete API key ${key}:`, err);
      setError(`Failed to delete ${key}. Please try again.`);
    }
  };

  const inputValue = (key: string): string => {
    if (apiKeys[key] !== undefined) return apiKeys[key];
    if (configured[key] && !visibleKeys[key]) return MASKED_PLACEHOLDER;
    return '';
  };

  const renderApiKeySection = (title: string, description: string, keys: ApiKeyDef[], icon: React.ReactNode) => (
    <Card className="bg-panel border-gray-700 dark:border-gray-700">
      <CardHeader>
        <CardTitle className="text-lg font-medium text-primary flex items-center gap-2">
          {icon}
          {title}
        </CardTitle>
        <p className="text-sm text-muted-foreground">{description}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        {keys.map((apiKey) => (
          <div key={apiKey.key} className="space-y-2">
            <div className="flex items-center gap-2">
              <button
                className="text-sm font-medium text-primary hover:text-blue-500 cursor-pointer transition-colors text-left"
                onClick={() => window.open(apiKey.url, '_blank')}
              >
                {apiKey.label}
              </button>
              {configured[apiKey.key] && (
                <span className="text-[10px] uppercase tracking-wide text-emerald-500/90 border border-emerald-500/30 rounded px-1.5 py-0.5">
                  Configured
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground">{apiKey.description}</p>
            <div className="relative">
              <Input
                type={visibleKeys[apiKey.key] ? 'text' : 'password'}
                placeholder={apiKey.placeholder}
                value={inputValue(apiKey.key)}
                disabled={revealing[apiKey.key]}
                onFocus={() => {
                  // Allow replacing a masked configured key without revealing first
                  if (configured[apiKey.key] && apiKeys[apiKey.key] === undefined) {
                    setApiKeys(prev => ({ ...prev, [apiKey.key]: '' }));
                    setVisibleKeys(prev => ({ ...prev, [apiKey.key]: true }));
                  }
                }}
                onChange={(e) => handleKeyChange(apiKey.key, e.target.value)}
                className="pr-20"
              />
              <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center gap-1">
                {(configured[apiKey.key] || apiKeys[apiKey.key]) && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 hover:bg-red-500/10 hover:text-red-500"
                    onClick={() => clearKey(apiKey.key)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  disabled={revealing[apiKey.key]}
                  onClick={() => toggleKeyVisibility(apiKey.key)}
                >
                  {visibleKeys[apiKey.key] ? (
                    <EyeOff className="h-3 w-3" />
                  ) : (
                    <Eye className="h-3 w-3" />
                  )}
                </Button>
              </div>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-primary mb-2">API Keys</h2>
        <p className="text-sm text-muted-foreground">
          Configure API credentials for language models and market data.
          OpenRouter is the primary LLM; Tiingo is secondary data (Alpaca SIP is primary via server env).
          Alpaca trading keys stay in server environment (paper only) and are not managed here.
          Changes are automatically saved.
          {loading ? ' Loading key status…' : ''}
        </p>
      </div>

      {error && (
        <Card className="bg-amber-500/5 border-amber-500/20">
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              <Key className="h-5 w-5 text-amber-500 mt-0.5 flex-shrink-0" />
              <div className="space-y-1">
                <h4 className="text-sm font-medium text-amber-500">Could not load key status</h4>
                <p className="text-xs text-muted-foreground">{error}</p>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setError(null);
                    loadApiKeys();
                  }}
                  className="text-xs mt-2 p-0 h-auto text-amber-500 hover:text-amber-400"
                >
                  Retry
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {renderApiKeySection(
        'Financial Data',
        'Tiingo is secondary market data. Alpaca SIP (primary prices) and Alpaca trading keys are server-env paper only — not editable here.',
        FINANCIAL_API_KEYS,
        <Key className="h-4 w-4" />
      )}

      {renderApiKeySection(
        'Language Models',
        'OpenRouter is the primary LLM provider. Other keys are optional fallbacks.',
        LLM_API_KEYS,
        <Key className="h-4 w-4" />
      )}

      <Card className="bg-amber-500/5 border-amber-500/20">
        <CardContent className="p-4">
          <div className="flex items-start gap-3">
            <Key className="h-5 w-5 text-amber-500 mt-0.5 flex-shrink-0" />
            <div className="space-y-1">
              <h4 className="text-sm font-medium text-amber-500">Security Note</h4>
              <p className="text-xs text-muted-foreground">
                Keys shown here are stored on the server. Full values are fetched only when you reveal them.
                Alpaca trading credentials remain in the deployment environment (paper trading only) and are never shown in this UI.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
