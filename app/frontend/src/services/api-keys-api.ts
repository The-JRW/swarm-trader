import { getApiBaseUrl } from '@/lib/api-base';

export interface ApiKey {
  id: number;
  provider: string;
  key_value: string;
  is_active: boolean;
  description?: string;
  created_at: string;
  updated_at?: string;
  last_used?: string;
}

export interface ApiKeySummary {
  id: number;
  provider: string;
  is_active: boolean;
  description?: string;
  created_at: string;
  updated_at?: string;
  last_used?: string;
  has_key: boolean;
}

export interface ApiKeyCreateRequest {
  provider: string;
  key_value: string;
  description?: string;
  is_active: boolean;
}

export interface ApiKeyUpdateRequest {
  key_value?: string;
  description?: string;
  is_active?: boolean;
}

export interface ApiKeyBulkUpdateRequest {
  api_keys: ApiKeyCreateRequest[];
}

class ApiKeysService {
  /** Resolve base URL per request — never cache at module load (SSR / https origin). */
  private getBaseUrl(): string {
    return `${getApiBaseUrl()}/api-keys`;
  }

  async getAllApiKeys(includeInactive = false): Promise<ApiKeySummary[]> {
    const params = new URLSearchParams();
    if (includeInactive) {
      params.append('include_inactive', 'true');
    }

    const response = await fetch(`${this.getBaseUrl()}?${params}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch API keys: ${response.statusText}`);
    }
    return response.json();
  }

  async getApiKey(provider: string): Promise<ApiKey> {
    const response = await fetch(`${this.getBaseUrl()}/${encodeURIComponent(provider)}`);
    if (!response.ok) {
      if (response.status === 404) {
        throw new Error('API key not found');
      }
      throw new Error(`Failed to fetch API key: ${response.statusText}`);
    }
    return response.json();
  }

  async createOrUpdateApiKey(request: ApiKeyCreateRequest): Promise<ApiKey> {
    const response = await fetch(this.getBaseUrl(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`Failed to create/update API key: ${response.statusText}`);
    }
    return response.json();
  }

  async updateApiKey(provider: string, request: ApiKeyUpdateRequest): Promise<ApiKey> {
    const response = await fetch(`${this.getBaseUrl()}/${encodeURIComponent(provider)}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error('API key not found');
      }
      throw new Error(`Failed to update API key: ${response.statusText}`);
    }
    return response.json();
  }

  async deleteApiKey(provider: string): Promise<void> {
    const response = await fetch(`${this.getBaseUrl()}/${encodeURIComponent(provider)}`, {
      method: 'DELETE',
    });

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error('API key not found');
      }
      throw new Error(`Failed to delete API key: ${response.statusText}`);
    }
  }

  async deactivateApiKey(provider: string): Promise<ApiKeySummary> {
    const response = await fetch(`${this.getBaseUrl()}/${encodeURIComponent(provider)}/deactivate`, {
      method: 'PATCH',
    });

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error('API key not found');
      }
      throw new Error(`Failed to deactivate API key: ${response.statusText}`);
    }
    return response.json();
  }

  async bulkUpdateApiKeys(request: ApiKeyBulkUpdateRequest): Promise<ApiKey[]> {
    const response = await fetch(`${this.getBaseUrl()}/bulk`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`Failed to bulk update API keys: ${response.statusText}`);
    }
    return response.json();
  }

  async updateLastUsed(provider: string): Promise<void> {
    const response = await fetch(`${this.getBaseUrl()}/${encodeURIComponent(provider)}/last-used`, {
      method: 'PATCH',
    });

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error('API key not found');
      }
      throw new Error(`Failed to update last used timestamp: ${response.statusText}`);
    }
  }
}

export const apiKeysService = new ApiKeysService();
