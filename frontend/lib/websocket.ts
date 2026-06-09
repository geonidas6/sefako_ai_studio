export interface WsEvent {
  type: 'round_start' | 'round_complete' | 'agent_start' | 'agent_complete' | 'agent_error' | 'workflow_complete' | 'workflow_error' | 'error' | 'ping';
  timestamp?: string;
  round?: number;
  message?: string;
  agent?: string;
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
  onError: (err: any) => void
): () => void {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const apiDomain = process.env.NEXT_PUBLIC_API_DOMAIN;
  const host = apiDomain || (
    window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
      ? 'localhost:8000'
      : `${window.location.hostname}:8000`
  );

  const socket = new WebSocket(`${protocol}//${host}/ws/projects/${projectId}`);

  socket.onopen = () => {
    // Start workflow
    socket.send(JSON.stringify({ action: 'start' }));
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
    onClose();
  };

  socket.onerror = (err) => {
    onError(err);
  };

  // Return a cleanup function to close connection
  return () => {
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
      socket.close();
    }
  };
}
