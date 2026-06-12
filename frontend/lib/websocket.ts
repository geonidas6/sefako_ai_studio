export interface WsEvent {
  type: 'workflow_started' | 'user_message' | 'round_start' | 'round_complete' | 'agent_start' | 'agent_complete' | 'employee_message' | 'agent_error' | 'workflow_complete' | 'workflow_error' | 'workflow_paused' | 'error' | 'ping';
  timestamp?: string;
  sequence?: number;
  round?: number;
  message?: string;
  content?: string;
  author?: string;
  agent?: string;
  department?: string;
  employee?: {
    name: string;
    role: string;
    avatar: string;
  };
  phase?: string;
  target?: string;
  error?: string;
  preview?: string;
  deliverables?: {
    cdc?: string;
    mcd?: string;
    architecture?: string;
    roadmap?: string;
    notes_synthese?: string;
  };
}

export function connectProjectWs(
  projectId: string,
  onEvent: (event: WsEvent) => void,
  onClose: () => void,
  onError: (err: any) => void,
  options: { reconnect?: boolean } = {}
): () => void {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const apiDomain = process.env.NEXT_PUBLIC_API_DOMAIN;
  const host = apiDomain || (
    window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
      ? 'localhost:8000'
      : `${window.location.hostname}:8000`
  );

  let socket: WebSocket | null = null;
  let manuallyClosed = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let retryCount = 0;

  const connect = () => {
    socket = new WebSocket(`${protocol}//${host}/ws/projects/${projectId}`);

    socket.onopen = () => {
      retryCount = 0;
    };

    socket.onmessage = (event) => {
      try {
        const data: WsEvent = JSON.parse(event.data);
        onEvent(data);
      } catch (err) {
        console.error('Error parsing WS message:', err);
      }
    };

    socket.onclose = () => {
      if (manuallyClosed) return;
      if (options.reconnect && retryCount < 8) {
        const delay = Math.min(1000 * 2 ** retryCount, 10000);
        retryCount += 1;
        reconnectTimer = setTimeout(connect, delay);
        return;
      }
      onClose();
    };

    socket.onerror = (err) => {
      if (!manuallyClosed && !options.reconnect) {
        onError(err);
      }
    };
  };

  connect();

  return () => {
    manuallyClosed = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      socket.close();
    }
  };
}
