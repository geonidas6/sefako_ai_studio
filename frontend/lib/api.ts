const API_BASE = '/api';

function getHeaders() {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

export async function request(path: string, options: RequestInit = {}) {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      ...getHeaders(),
      ...options.headers,
    },
  });

  if (!response.ok) {
    let errorMsg = 'Une erreur est survenue';
    try {
      const data = await response.json();
      errorMsg = data.detail || errorMsg;
    } catch {
      // ignore
    }
    throw new Error(errorMsg);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export const api = {
  auth: {
    async login(username: string, password: string) {
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);

      const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData,
      });

      if (!response.ok) {
        let errorMsg = 'Identifiants incorrects';
        try {
          const data = await response.json();
          errorMsg = data.detail || errorMsg;
        } catch {
          // ignore
        }
        throw new Error(errorMsg);
      }

      const data = await response.json();
      if (typeof window !== 'undefined') {
        localStorage.setItem('token', data.access_token);
        localStorage.setItem('username', data.username);
      }
      return data;
    },

    logout() {
      if (typeof window !== 'undefined') {
        localStorage.removeItem('token');
        localStorage.removeItem('username');
      }
    },

    isLoggedIn() {
      if (typeof window !== 'undefined') {
        return !!localStorage.getItem('token');
      }
      return false;
    },

    async checkAdminExists() {
      return request('/auth/me');
    }
  },

  projects: {
    async list() {
      return request('/projects');
    },
    async create(title: string, inputText: string) {
      return request('/projects', {
        method: 'POST',
        body: JSON.stringify({ title, input_text: inputText }),
      });
    },
    async get(id: string) {
      return request(`/projects/${id}`);
    },
    async delete(id: string) {
      return request(`/projects/${id}`, {
        method: 'DELETE',
      });
    }
  },

  admin: {
    async getConfigs() {
      return request('/admin/llm-config');
    },
    async updateConfig(provider: string, data: { is_enabled: boolean; active_model?: string; api_key?: string }) {
      return request(`/admin/llm-config/${provider}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      });
    },
    async addModel(provider: string, model: string) {
      return request(`/admin/llm-config/${provider}/models`, {
        method: 'POST',
        body: JSON.stringify({ model }),
      });
    },
    async getAssignments() {
      return request('/admin/llm-config/assignments');
    },
    async updateAssignment(agent: string, provider: string) {
      return request('/admin/llm-config/assignments', {
        method: 'PUT',
        body: JSON.stringify({ agent, provider }),
      });
    },
    async testConnection(provider: string, apiKey: string, model: string) {
      return request('/admin/llm-config/test', {
        method: 'POST',
        body: JSON.stringify({ provider, api_key: apiKey, model }),
      });
    },
    async getCosts() {
      return request('/admin/llm-config/costs');
    }
  }
};
