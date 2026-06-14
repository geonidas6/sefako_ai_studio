'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import Editor from '@monaco-editor/react';
import {
  ArrowLeft,
  Bot,
  ChevronRight,
  Copy,
  Download,
  FileCode,
  FileCode2,
  FilePlus2,
  Folder,
  FolderPlus,
  FolderTree,
  Loader2,
  PanelRightOpen,
  RefreshCw,
  Save,
  Search,
  Send,
  Sparkles,
  TerminalSquare,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import { api } from '../../../../lib/api';
import { connectProjectWs, WsEvent } from '../../../../lib/websocket';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

type WorkspaceEntry = {
  path: string;
  name: string;
  is_dir?: boolean;
  kind?: string;
};

type LogLine = {
  text: string;
  type?: 'info' | 'success' | 'error' | 'system';
};

type ConversationItem = {
  kind?: 'agent' | 'user';
  agent: string;
  department: string;
  employee: { name: string; role: string; avatar: string };
  message: string;
  round?: number;
  phase?: string;
  target?: string;
  timestamp?: string;
};

type OpenFile = {
  path: string;
  name: string;
  content: string;
  originalContent: string;
  isDirty: boolean;
};

type WorkspaceTreeNode = {
  path: string;
  name: string;
  isDir: boolean;
  children: WorkspaceTreeNode[];
};

function normalizeWorkspacePath(path: string = ''): string {
  return path.replace(/^\/+|\/+$/g, '');
}

function getAncestorPaths(path: string = ''): string[] {
  const cleaned = normalizeWorkspacePath(path);
  if (!cleaned) return [];
  const segments = cleaned.split('/');
  const ancestors: string[] = [];
  let current = '';
  for (let index = 0; index < segments.length - 1; index += 1) {
    current = current ? `${current}/${segments[index]}` : segments[index];
    ancestors.push(current);
  }
  return ancestors;
}

function sortWorkspaceTree(nodes: WorkspaceTreeNode[]): WorkspaceTreeNode[] {
  return [...nodes]
    .sort((left, right) => {
      if (left.isDir !== right.isDir) return left.isDir ? -1 : 1;
      return left.name.localeCompare(right.name, 'fr', { sensitivity: 'base' });
    })
    .map((node) => ({ ...node, children: sortWorkspaceTree(node.children) }));
}

function buildWorkspaceTree(entries: WorkspaceEntry[]): WorkspaceTreeNode[] {
  const root: WorkspaceTreeNode = { path: '', name: '', isDir: true, children: [] };
  const lookup = new Map<string, WorkspaceTreeNode>([['', root]]);
  const sortedEntries = [...entries].sort((left, right) => left.path.localeCompare(right.path, 'fr', { sensitivity: 'base' }));

  for (const entry of sortedEntries) {
    const cleaned = normalizeWorkspacePath(entry.path);
    if (!cleaned) continue;

    const segments = cleaned.split('/');
    let parent = root;
    let currentPath = '';

    segments.forEach((segment, index) => {
      currentPath = currentPath ? `${currentPath}/${segment}` : segment;
      const isLeaf = index === segments.length - 1;
      const shouldBeDir = !isLeaf || Boolean(entry.is_dir);
      let node = lookup.get(currentPath);

      if (!node) {
        node = {
          path: currentPath,
          name: segment,
          isDir: shouldBeDir,
          children: [],
        };
        lookup.set(currentPath, node);
        parent.children.push(node);
      } else if (shouldBeDir) {
        node.isDir = true;
      }

      parent = node;
    });
  }

  return sortWorkspaceTree(root.children);
}

function getLanguage(filename: string = ''): string {
  const lower = filename.toLowerCase();
  if (lower.endsWith('.tsx') || lower.endsWith('.ts')) return 'typescript';
  if (lower.endsWith('.jsx') || lower.endsWith('.js')) return 'javascript';
  if (lower.endsWith('.py')) return 'python';
  if (lower.endsWith('.json')) return 'json';
  if (lower.endsWith('.md')) return 'markdown';
  if (lower.endsWith('.yml') || lower.endsWith('.yaml')) return 'yaml';
  if (lower.endsWith('.css')) return 'css';
  if (lower.endsWith('.html')) return 'html';
  if (lower.endsWith('.sh') || lower === '.env' || lower.endsWith('.env')) return 'shell';
  if (lower.endsWith('dockerfile') || lower === 'dockerfile') return 'dockerfile';
  return 'plaintext';
}

export default function ProjectWorkspaceIdePage() {
  const params = useParams();
  const projectId = params.id as string;
  const editorRef = useRef<any>(null);
  const wsCleanupRef = useRef<(() => void) | null>(null);
  const seenEventSequencesRef = useRef<Set<number>>(new Set());
  const logsEndRef = useRef<HTMLDivElement>(null);

  const [project, setProject] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [isAdminSession, setIsAdminSession] = useState(false);

  const [workspaceFiles, setWorkspaceFiles] = useState<WorkspaceEntry[]>([]);
  const [selectedEntryPath, setSelectedEntryPath] = useState('');
  const [loadingWorkspaceFiles, setLoadingWorkspaceFiles] = useState(false);
  const [creatingWorkspaceEntry, setCreatingWorkspaceEntry] = useState(false);
  const [newWorkspacePath, setNewWorkspacePath] = useState('');
  const [workspaceMovePath, setWorkspaceMovePath] = useState('');
  const [fileFilter, setFileFilter] = useState('');
  const [expandedDirs, setExpandedDirs] = useState<Record<string, boolean>>({});

  const [openFiles, setOpenFiles] = useState<OpenFile[]>([]);
  const [activeFileIndex, setActiveFileIndex] = useState(-1);
  const [loadingFilePath, setLoadingFilePath] = useState('');
  const [savingWorkspaceFile, setSavingWorkspaceFile] = useState(false);
  const [startingTechnicalDesign, setStartingTechnicalDesign] = useState(false);
  const [startingImplementation, setStartingImplementation] = useState(false);
  const [downloadingWorkspace, setDownloadingWorkspace] = useState(false);
  const [downloadingMarkdown, setDownloadingMarkdown] = useState(false);
  const [copyingHostExportCommand, setCopyingHostExportCommand] = useState(false);
  const [hostExportCommand, setHostExportCommand] = useState<{ command: string; destination: string } | null>(null);

  const [logs, setLogs] = useState<LogLine[]>([]);
  const [conversation, setConversation] = useState<ConversationItem[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [sendingMessage, setSendingMessage] = useState(false);
  const [agentStatuses, setAgentStatuses] = useState<Record<string, string>>({});
  const [runningAgents, setRunningAgents] = useState<Record<string, boolean>>({});
  const [wsStatus, setWsStatus] = useState<'connecting' | 'running' | 'idle' | 'error' | 'paused'>('idle');
  const [teamDrawerOpen, setTeamDrawerOpen] = useState(false);

  const implementationPipeline = project?.final_deliverables?.implementation_pipeline || null;
  const workspaceInfo = project?.final_deliverables?.implementation_workspace || (implementationPipeline?.project_dir ? {
    project_dir: implementationPipeline.project_dir,
    root_path: implementationPipeline.root_path || '',
    files: implementationPipeline.generated_files || [],
    repo_name: implementationPipeline.project_dir.split('/').filter(Boolean).pop() || 'workspace',
  } : null);
  const selectedWorkspaceEntry = workspaceFiles.find((entry) => entry.path === selectedEntryPath) || null;
  const activeFile = activeFileIndex >= 0 ? openFiles[activeFileIndex] : null;

  const employeeRoster = [
    { agent: 'strategy', department: 'Stratégie', name: 'Aminata', role: 'Lead Growth', avatar: 'AG' },
    { agent: 'strategy', department: 'Stratégie', name: 'Noam', role: 'Analyste marché', avatar: 'NM' },
    { agent: 'ux', department: 'UX', name: 'Maya', role: 'UX Researcher', avatar: 'UX' },
    { agent: 'ux', department: 'UX', name: 'Lina', role: 'Product Designer', avatar: 'PD' },
    { agent: 'engineering', department: 'Ingénierie', name: 'Elias', role: 'Architecte logiciel', avatar: 'AR' },
    { agent: 'engineering', department: 'Ingénierie', name: 'Sara', role: 'Data modeler', avatar: 'DB' },
    { agent: 'devops', department: 'DevOps', name: 'Karim', role: 'DevSecOps', avatar: 'DS' },
    { agent: 'devops', department: 'DevOps', name: 'Inès', role: 'Cloud engineer', avatar: 'CE' },
  ];

  const filteredFiles = useMemo(() => {
    const query = fileFilter.trim().toLowerCase();
    if (!query) return workspaceFiles;
    return workspaceFiles.filter((entry) => entry.path.toLowerCase().includes(query));
  }, [fileFilter, workspaceFiles]);

  const workspaceTree = useMemo(() => buildWorkspaceTree(filteredFiles), [filteredFiles]);

  useEffect(() => {
    setExpandedDirs((prev) => {
      const next = { ...prev };
      workspaceTree.forEach((node) => {
        if (next[node.path] === undefined) next[node.path] = true;
      });
      if (fileFilter.trim()) {
        workspaceFiles.forEach((entry) => {
          if (entry.is_dir) next[entry.path] = true;
        });
      }
      getAncestorPaths(selectedEntryPath).forEach((ancestor) => {
        next[ancestor] = true;
      });
      return next;
    });
  }, [workspaceTree, fileFilter, workspaceFiles, selectedEntryPath]);

  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  useEffect(() => {
    setIsAdminSession(api.auth.isLoggedIn());
  }, []);

  const loadProject = useCallback(async () => {
    try {
      const data = await api.projects.get(projectId);
      setProject(data);
      if (!data?.final_deliverables?.implementation_workspace) {
        setError("Le workspace applicatif n'est pas encore initialisé pour ce projet.");
      }
    } catch (err: any) {
      setError(err.message || 'Impossible de charger le projet.');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadProject();
    return () => {
      if (wsCleanupRef.current) wsCleanupRef.current();
    };
  }, [loadProject]);

  const loadWorkspaceTree = useCallback(async (preferredPath?: string) => {
    setLoadingWorkspaceFiles(true);
    try {
      const data = await api.projects.getWorkspaceTree(projectId);
      const files = data.files || [];
      setWorkspaceFiles(files);
      const nextPath =
        preferredPath ||
        (files.find((entry: WorkspaceEntry) => entry.path === selectedEntryPath)?.path ?? selectedEntryPath) ||
        files[0]?.path ||
        '';
      if (nextPath) {
        setSelectedEntryPath(nextPath);
        setWorkspaceMovePath(nextPath);
      }
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible de charger les fichiers du workspace.', type: 'error' }]);
    } finally {
      setLoadingWorkspaceFiles(false);
    }
  }, [projectId, selectedEntryPath]);

  useEffect(() => {
    if (!isAdminSession || !workspaceInfo?.project_dir) return;
    void loadWorkspaceTree();
  }, [isAdminSession, workspaceInfo?.project_dir, loadWorkspaceTree]);

  const openWorkspaceFile = useCallback(async (entry: WorkspaceEntry) => {
    setSelectedEntryPath(entry.path);
    setWorkspaceMovePath(entry.path);

    if (entry.is_dir) {
      return;
    }

    const existingIndex = openFiles.findIndex((file) => file.path === entry.path);
    if (existingIndex >= 0) {
      setActiveFileIndex(existingIndex);
      return;
    }

    setLoadingFilePath(entry.path);
    try {
      const data = await api.projects.getWorkspaceFile(projectId, entry.path);
      const nextFile: OpenFile = {
        path: entry.path,
        name: entry.name,
        content: data.content || '',
        originalContent: data.content || '',
        isDirty: false,
      };
      setOpenFiles((prev) => {
        const next = [...prev, nextFile];
        setActiveFileIndex(next.length - 1);
        return next;
      });
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible de charger ce fichier.', type: 'error' }]);
    } finally {
      setLoadingFilePath('');
    }
  }, [openFiles, projectId]);

  const closeFile = (index: number, event?: React.MouseEvent) => {
    event?.stopPropagation();
    setOpenFiles((prev) => {
      const next = prev.filter((_, i) => i !== index);
      setActiveFileIndex((current) => {
        if (next.length === 0) return -1;
        if (current === index) return Math.max(0, index - 1);
        if (current > index) return current - 1;
        return current;
      });
      return next;
    });
  };

  const refreshCleanOpenFiles = useCallback(async () => {
    const refreshableFiles = openFiles.filter((file) => !file.isDirty);
    if (!refreshableFiles.length) return;

    const refreshed = await Promise.all(
      refreshableFiles.map(async (file) => {
        try {
          const data = await api.projects.getWorkspaceFile(projectId, file.path);
          return [file.path, data.content || ''] as const;
        } catch {
          return [file.path, null] as const;
        }
      })
    );

    const refreshedMap = new Map(
      refreshed.filter((item): item is readonly [string, string] => item[1] !== null)
    );

    if (!refreshedMap.size) return;

    setOpenFiles((prev) => prev.map((file) => {
      if (file.isDirty || !refreshedMap.has(file.path)) return file;
      const content = refreshedMap.get(file.path) || '';
      return {
        ...file,
        content,
        originalContent: content,
        isDirty: false,
      };
    }));
  }, [openFiles, projectId]);

  const handleEditorChange = (value?: string) => {
    const content = value || '';
    setOpenFiles((prev) => prev.map((file, index) => (
      index === activeFileIndex
        ? { ...file, content, isDirty: content !== file.originalContent }
        : file
    )));
  };

  const handleSaveWorkspaceFile = useCallback(async () => {
    if (!activeFile) return;
    setSavingWorkspaceFile(true);
    try {
      await api.projects.saveWorkspaceFile(projectId, activeFile.path, activeFile.content);
      setOpenFiles((prev) => prev.map((file, index) => (
        index === activeFileIndex
          ? { ...file, originalContent: file.content, isDirty: false }
          : file
      )));
      setLogs((prev) => [...prev, { text: `Fichier sauvegardé: ${activeFile.path}`, type: 'success' }]);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible de sauvegarder ce fichier.', type: 'error' }]);
    } finally {
      setSavingWorkspaceFile(false);
    }
  }, [activeFile, activeFileIndex, projectId]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        if (activeFile?.isDirty && !savingWorkspaceFile) {
          void handleSaveWorkspaceFile();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeFile, savingWorkspaceFile, handleSaveWorkspaceFile]);

  const handleCreateWorkspaceEntry = async (isDirectory: boolean) => {
    const filePath = newWorkspacePath.trim();
    if (!filePath) return;
    setCreatingWorkspaceEntry(true);
    try {
      await api.projects.createWorkspaceEntry(projectId, filePath, isDirectory, '');
      await loadWorkspaceTree(filePath);
      setNewWorkspacePath('');
      setLogs((prev) => [...prev, { text: `${isDirectory ? 'Dossier' : 'Fichier'} créé: ${filePath}`, type: 'success' }]);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || `Impossible de créer le ${isDirectory ? 'dossier' : 'fichier'}.`, type: 'error' }]);
    } finally {
      setCreatingWorkspaceEntry(false);
    }
  };

  const handleDeleteWorkspaceEntry = async () => {
    if (!selectedEntryPath) return;
    const confirmed = window.confirm(`Supprimer ${selectedEntryPath} du workspace projet ?`);
    if (!confirmed) return;
    setCreatingWorkspaceEntry(true);
    try {
      const deletedPath = selectedEntryPath;
      await api.projects.deleteWorkspaceEntry(projectId, deletedPath);
      setOpenFiles((prev) => prev.filter((file) => file.path !== deletedPath));
      setActiveFileIndex((current) => {
        const nextOpenFiles = openFiles.filter((file) => file.path !== deletedPath);
        if (!nextOpenFiles.length) return -1;
        return Math.min(current, nextOpenFiles.length - 1);
      });
      setSelectedEntryPath('');
      await loadWorkspaceTree();
      setLogs((prev) => [...prev, { text: `Entrée supprimée: ${deletedPath}`, type: 'success' }]);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible de supprimer cette entrée.', type: 'error' }]);
    } finally {
      setCreatingWorkspaceEntry(false);
    }
  };

  const handleMoveWorkspaceEntry = async () => {
    const oldPath = selectedEntryPath.trim();
    const newPath = workspaceMovePath.trim();
    if (!oldPath || !newPath || oldPath === newPath) return;
    setCreatingWorkspaceEntry(true);
    try {
      await api.projects.moveWorkspaceEntry(projectId, oldPath, newPath);
      setOpenFiles((prev) => prev.map((file) => (
        file.path === oldPath
          ? { ...file, path: newPath, name: newPath.split('/').pop() || newPath }
          : file
      )));
      setSelectedEntryPath(newPath);
      await loadWorkspaceTree(newPath);
      setLogs((prev) => [...prev, { text: `Entrée déplacée: ${oldPath} -> ${newPath}`, type: 'success' }]);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible de renommer cette entrée.', type: 'error' }]);
    } finally {
      setCreatingWorkspaceEntry(false);
    }
  };

  const handleSendMessage = async () => {
    const content = chatInput.trim();
    if (!content) return;
    setSendingMessage(true);
    try {
      await api.projects.sendMessage(projectId, content);
      setChatInput('');
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || "Impossible d'envoyer le message.", type: 'error' }]);
    } finally {
      setSendingMessage(false);
    }
  };

  const handleStartImplementation = async () => {
    setStartingImplementation(true);
    try {
      await api.projects.startImplementation(projectId, true);
      setLogs((prev) => [...prev, { text: "Phase applicative lancée depuis l'IDE.", type: 'success' }]);
      await loadProject();
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible de lancer la phase applicative.', type: 'error' }]);
    } finally {
      setStartingImplementation(false);
    }
  };

  const handleStartTechnicalDesign = async () => {
    setStartingTechnicalDesign(true);
    try {
      const updatedProject = await api.projects.startTechnicalDesign(projectId, true);
      setProject(updatedProject);
      setLogs((prev) => [...prev, { text: 'Conception technique initialisée depuis l’IDE.', type: 'success' }]);
      await loadProject();
      await loadWorkspaceTree();
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible d’initialiser la conception technique.', type: 'error' }]);
    } finally {
      setStartingTechnicalDesign(false);
    }
  };

  const handleDownloadWorkspace = async () => {
    setDownloadingWorkspace(true);
    try {
      await api.projects.downloadWorkspaceArchive(projectId);
      setLogs((prev) => [...prev, { text: 'Archive workspace téléchargée.', type: 'success' }]);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible de télécharger le workspace.', type: 'error' }]);
    } finally {
      setDownloadingWorkspace(false);
    }
  };

  const handleDownloadMarkdown = async () => {
    setDownloadingMarkdown(true);
    try {
      await api.projects.downloadMarkdownExport(projectId);
      setLogs((prev) => [...prev, { text: 'Export Markdown téléchargé.', type: 'success' }]);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || 'Impossible de télécharger le Markdown.', type: 'error' }]);
    } finally {
      setDownloadingMarkdown(false);
    }
  };

  const handleCopyHostExportCommand = async () => {
    setCopyingHostExportCommand(true);
    try {
      const data = await api.projects.getWorkspaceHostExportCommand(projectId);
      await navigator.clipboard.writeText(data.command);
      setHostExportCommand({ command: data.command, destination: data.destination });
      setLogs((prev) => [...prev, {
        text: `Commande export /opt copiée. Destination: ${data.destination}`,
        type: 'success',
      }]);
    } catch (err: any) {
      setLogs((prev) => [...prev, { text: err.message || "Impossible de préparer l'export vers /opt.", type: 'error' }]);
    } finally {
      setCopyingHostExportCommand(false);
    }
  };

  const handleWsEvent = (event: WsEvent) => {
    if (event.sequence && seenEventSequencesRef.current.has(event.sequence)) return;
    if (event.sequence) seenEventSequencesRef.current.add(event.sequence);

    switch (event.type) {
      case 'workflow_started':
        setWsStatus('running');
        setLogs((prev) => [...prev, { text: event.message || 'Analyse lancée.', type: 'system' }]);
        break;
      case 'workflow_complete':
      case 'implementation_complete':
        setWsStatus('idle');
        if (event.deliverables) {
          setProject((prev: any) => prev ? {
            ...prev,
            status: 'completed',
            final_deliverables: {
              ...(prev.final_deliverables || {}),
              ...event.deliverables,
            },
          } : prev);
        }
        if (event.pipeline || event.workspace) {
          setProject((prev: any) => prev ? {
            ...prev,
            final_deliverables: {
              ...(prev.final_deliverables || {}),
              ...(event.pipeline ? { implementation_pipeline: event.pipeline } : {}),
              ...(event.workspace ? { implementation_workspace: event.workspace } : {}),
            },
          } : prev);
        }
        setLogs((prev) => [...prev, { text: event.message || 'Phase terminée.', type: 'success' }]);
        void loadWorkspaceTree(selectedEntryPath);
        void refreshCleanOpenFiles();
        break;
      case 'workflow_error':
      case 'implementation_error':
      case 'agent_error':
        setWsStatus('error');
        setLogs((prev) => [...prev, { text: event.error || event.message || 'Erreur de workflow.', type: 'error' }]);
        break;
      case 'workflow_paused':
        setWsStatus('paused');
        setLogs((prev) => [...prev, { text: event.message || 'Workflow mis en pause.', type: 'system' }]);
        break;
      case 'agent_start': {
        const agentKey = event.agent;
        if (agentKey) {
          setRunningAgents((prev) => ({ ...prev, [agentKey]: true }));
          setAgentStatuses((prev) => ({ ...prev, [agentKey]: 'Travaille' }));
        }
        setLogs((prev) => [...prev, { text: `[${event.agent?.toUpperCase()}] Début du travail...`, type: 'info' }]);
        break;
      }
      case 'agent_complete': {
        const agentKey = event.agent;
        if (agentKey) {
          setRunningAgents((prev) => ({ ...prev, [agentKey]: false }));
          setAgentStatuses((prev) => ({ ...prev, [agentKey]: 'Disponible' }));
        }
        setLogs((prev) => [...prev, { text: `[${event.agent?.toUpperCase()}] Travail terminé.`, type: 'success' }]);
        break;
      }
      case 'employee_message': {
        const agentKey = event.agent;
        const departmentKey = event.department;
        const employee = event.employee;
        const message = event.message;
        if (employee && message && agentKey && departmentKey) {
          setConversation((prev) => [...prev, {
            kind: 'agent',
            agent: agentKey,
            department: departmentKey,
            employee,
            message,
            round: event.round,
            phase: event.phase,
            target: event.target,
            timestamp: event.timestamp,
          }]);
        }
        break;
      }
      case 'user_message':
        if (event.content || event.message) {
          setConversation((prev) => [...prev, {
            kind: 'user',
            agent: 'user',
            department: 'Client',
            employee: { name: event.author || 'Utilisateur', role: 'Client / chef de projet', avatar: 'US' },
            message: event.content || event.message || '',
            timestamp: event.timestamp,
          }]);
        }
        break;
      case 'implementation_status':
        if (event.pipeline || event.workspace) {
          setProject((prev: any) => prev ? {
            ...prev,
            final_deliverables: {
              ...(prev.final_deliverables || {}),
              ...(event.pipeline ? { implementation_pipeline: event.pipeline } : {}),
              ...(event.workspace ? { implementation_workspace: event.workspace } : {}),
            },
          } : prev);
        }
        setLogs((prev) => [...prev, { text: event.message || 'Mise à jour du workspace.', type: 'system' }]);
        void loadWorkspaceTree(selectedEntryPath);
        void refreshCleanOpenFiles();
        break;
      case 'error':
        setWsStatus('error');
        setLogs((prev) => [...prev, { text: event.message || 'Connexion interrompue.', type: 'error' }]);
        break;
      default:
        break;
    }
  };

  useEffect(() => {
    if (!projectId) return;
    if (wsCleanupRef.current) wsCleanupRef.current();

    setWsStatus('connecting');
    setLogs((prev) => prev.some((item) => item.text === 'Connexion au canal IDE...') ? prev : [...prev, { text: 'Connexion au canal IDE...', type: 'system' }]);

    wsCleanupRef.current = connectProjectWs(
      projectId,
      handleWsEvent,
      () => {
        setWsStatus('idle');
        setLogs((prev) => [...prev, { text: 'Connexion IDE interrompue.', type: 'system' }]);
      },
      () => {
        setWsStatus('error');
        setLogs((prev) => [...prev, { text: 'Impossible de connecter le flux temps réel.', type: 'error' }]);
      },
      { reconnect: true }
    );

    return () => {
      if (wsCleanupRef.current) wsCleanupRef.current();
    };
  }, [projectId, selectedEntryPath]);

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-80px)] flex items-center justify-center p-8">
        <Loader2 className="h-7 w-7 animate-spin text-primary" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-3xl mx-auto p-6 md:p-10">
        <Card className="border-destructive/20">
          <CardHeader>
            <CardTitle className="text-destructive">IDE indisponible</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
          <CardContent className="flex gap-3">
            <Button asChild variant="outline">
              <Link href={`/projects/${projectId}`}>Retour au projet</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!isAdminSession) {
    return (
      <div className="max-w-3xl mx-auto p-6 md:p-10">
        <Card>
          <CardHeader>
            <CardTitle>Accès administrateur requis</CardTitle>
            <CardDescription>Cette page IDE est réservée à l'administration, car elle permet de modifier le repo réel du projet.</CardDescription>
          </CardHeader>
          <CardContent className="flex gap-3">
            <Button asChild>
              <Link href="/admin/login">Se connecter</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href={`/projects/${projectId}`}>Retour au projet</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-72px)] bg-background px-4 py-4 md:px-6">
      <div className="mx-auto flex h-[calc(100vh-104px)] max-w-[1900px] flex-col gap-4">
        <div className="rounded-[28px] border border-border/60 bg-muted/20 px-4 py-4 md:px-6">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                <FolderTree className="h-6 w-6" />
              </div>
              <div>
                <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.24em] text-muted-foreground">
                  <span>IDE applicatif</span>
                  <span className="h-1 w-1 rounded-full bg-border" />
                  <span>{workspaceInfo?.project_dir || 'workspace'}</span>
                </div>
                <h1 className="text-2xl font-bold tracking-tight text-foreground">{project?.title}</h1>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              {implementationPipeline?.status && (
                <div className={cn(
                  'rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-widest',
                  implementationPipeline.status === 'running'
                    ? 'border-primary/30 bg-primary/10 text-primary'
                    : implementationPipeline.status === 'completed'
                      ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                      : 'border-border/60 bg-muted/30 text-muted-foreground'
                )}>
                  Pipeline: {implementationPipeline.status}
                </div>
              )}
              {!workspaceInfo && (
                <Button type="button" variant="outline" className="gap-2" disabled={startingTechnicalDesign} onClick={handleStartTechnicalDesign}>
                  {startingTechnicalDesign ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderTree className="h-4 w-4" />}
                  Initialiser la conception technique
                </Button>
              )}
              {workspaceInfo && implementationPipeline?.status !== 'completed' && implementationPipeline?.status !== 'running' && (
                <Button type="button" variant="outline" className="gap-2" disabled={startingImplementation} onClick={handleStartImplementation}>
                  {startingImplementation ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  Lancer la phase applicative
                </Button>
              )}
              {implementationPipeline?.status === 'running' && (
                <div className="flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3 py-2 text-xs font-semibold uppercase tracking-widest text-primary">
                  <span className="h-2 w-2 rounded-full bg-primary animate-ping" />
                  Travaux en cours
                </div>
              )}
              <Button asChild variant="outline" className="gap-2">
                <Link href={`/projects/${projectId}`}>
                  <ArrowLeft className="h-4 w-4" />
                  Retour au projet
                </Link>
              </Button>
              <Button type="button" variant="outline" className="gap-2" onClick={() => loadWorkspaceTree(selectedEntryPath)}>
                <RefreshCw className={cn('h-4 w-4', loadingWorkspaceFiles && 'animate-spin')} />
                Actualiser
              </Button>
              <Button type="button" variant="outline" className="gap-2" onClick={() => setTeamDrawerOpen(true)}>
                <PanelRightOpen className="h-4 w-4" />
                Équipe & logs
              </Button>
              <Button type="button" variant="outline" className="gap-2" disabled={downloadingMarkdown} onClick={handleDownloadMarkdown}>
                {downloadingMarkdown ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                Export markdown
              </Button>
              <Button type="button" variant="outline" className="gap-2" disabled={!workspaceInfo || downloadingWorkspace} onClick={handleDownloadWorkspace}>
                {downloadingWorkspace ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                Télécharger ZIP
              </Button>
              <Button type="button" variant="outline" className="gap-2" disabled={!workspaceInfo || copyingHostExportCommand} onClick={handleCopyHostExportCommand}>
                {copyingHostExportCommand ? <Loader2 className="h-4 w-4 animate-spin" /> : <Copy className="h-4 w-4" />}
                Préparer export /opt
              </Button>
              <Button
                type="button"
                className="gap-2"
                disabled={!activeFile || !activeFile.isDirty || savingWorkspaceFile}
                onClick={handleSaveWorkspaceFile}
              >
                {savingWorkspaceFile ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Enregistrer
              </Button>
            </div>
          </div>
          {hostExportCommand && (
            <div className="mt-4 rounded-2xl border border-primary/30 bg-primary/5 p-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-bold uppercase tracking-[0.24em] text-primary">Commande à lancer sur le VPS</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    La commande a été copiée. Colle-la dans ton terminal SSH pour exporter le workspace vers{' '}
                    <span className="font-mono text-foreground">{hostExportCommand.destination}</span>.
                  </p>
                  <pre className="mt-3 overflow-x-auto rounded-xl border border-border/60 bg-black/70 p-3 text-xs text-zinc-100">
                    <code>{hostExportCommand.command}</code>
                  </pre>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="gap-2"
                  onClick={async () => {
                    await navigator.clipboard.writeText(hostExportCommand.command);
                    setLogs((prev) => [...prev, { text: 'Commande export /opt recopiée.', type: 'success' }]);
                  }}
                >
                  <Copy className="h-4 w-4" />
                  Copier
                </Button>
              </div>
            </div>
          )}
        </div>

        <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
          <Card className="min-h-0 overflow-hidden border-border/60 bg-muted/20">
            <CardHeader className="border-b border-border/40 pb-4">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <input
                  type="text"
                  value={fileFilter}
                  onChange={(event) => setFileFilter(event.target.value)}
                  placeholder="Filtrer les fichiers..."
                  className="h-10 w-full rounded-xl border border-border/60 bg-background pl-9 pr-3 text-sm outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-[0.24em] text-muted-foreground">Explorer</span>
                <span className="text-[10px] text-muted-foreground">{filteredFiles.length} entrée(s)</span>
              </div>
              <div className="space-y-2 rounded-2xl border border-border/60 bg-background/60 p-3">
                <div className="text-[10px] font-bold uppercase tracking-[0.24em] text-muted-foreground">Nouveau dans le workspace</div>
                <input
                  value={newWorkspacePath}
                  onChange={(event) => setNewWorkspacePath(event.target.value)}
                  placeholder="src/app/page.tsx ou docs"
                  className="h-10 w-full rounded-xl border border-border/60 bg-background px-3 text-sm outline-none focus:ring-1 focus:ring-primary"
                />
                <div className="flex shrink-0 gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    className="flex-1 gap-2"
                    disabled={creatingWorkspaceEntry || !newWorkspacePath.trim()}
                    onClick={() => handleCreateWorkspaceEntry(false)}
                  >
                    {creatingWorkspaceEntry ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FilePlus2 className="h-3.5 w-3.5" />}
                    Fichier
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="flex-1 gap-2"
                    disabled={creatingWorkspaceEntry || !newWorkspacePath.trim()}
                    onClick={() => handleCreateWorkspaceEntry(true)}
                  >
                    <FolderPlus className="h-3.5 w-3.5" />
                    Dossier
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="min-h-0 overflow-y-auto p-2">
              {loadingWorkspaceFiles ? (
                <div className="flex items-center justify-center py-8 text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              ) : filteredFiles.length === 0 ? (
                <div className="p-4 text-sm text-muted-foreground">Aucune entrée détectée.</div>
              ) : (
                <div className="space-y-1">
                  {workspaceTree.map((node) => {
                    const renderNode = (treeNode: WorkspaceTreeNode, depth = 0): React.ReactNode => {
                      const entry = workspaceFiles.find((item) => item.path === treeNode.path) || {
                        path: treeNode.path,
                        name: treeNode.name,
                        is_dir: treeNode.isDir,
                      };
                      const isExpanded = expandedDirs[treeNode.path] ?? depth === 0;
                      const isSelected = selectedEntryPath === treeNode.path;
                      const hasChildren = treeNode.children.length > 0;

                      return (
                        <div key={treeNode.path}>
                          <button
                            type="button"
                            onClick={() => {
                              void openWorkspaceFile(entry);
                              if (treeNode.isDir && hasChildren) {
                                setExpandedDirs((prev) => ({ ...prev, [treeNode.path]: !isExpanded }));
                              }
                            }}
                            className={cn(
                              'flex w-full items-center gap-2 rounded-xl py-2 pr-3 text-left text-sm transition-colors',
                              isSelected
                                ? 'bg-primary/10 text-primary'
                                : 'text-muted-foreground hover:bg-background/70 hover:text-foreground'
                            )}
                            style={{ paddingLeft: `${12 + depth * 16}px` }}
                          >
                            <ChevronRight className={cn('h-3.5 w-3.5 shrink-0 opacity-50 transition-transform', treeNode.isDir ? '' : 'opacity-0', treeNode.isDir && isExpanded && 'rotate-90')} />
                            {treeNode.isDir ? <Folder className="h-4 w-4 shrink-0" /> : <FileCode2 className="h-4 w-4 shrink-0" />}
                            <span className="min-w-0 flex-1 truncate">{treeNode.name}</span>
                            {treeNode.isDir && hasChildren ? (
                              <span className="text-[10px] uppercase tracking-widest text-muted-foreground/70">{treeNode.children.length}</span>
                            ) : null}
                          </button>
                          {treeNode.isDir && isExpanded && hasChildren ? (
                            <div>{treeNode.children.map((child) => renderNode(child, depth + 1))}</div>
                          ) : null}
                        </div>
                      );
                    };

                    return renderNode(node);
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="min-h-0 overflow-hidden border-border/60 bg-[#05070d]">
            <div className="flex min-h-0 h-full flex-col">
              <div className="border-b border-border/40 px-4 py-3">
                <div className="flex items-center justify-between gap-3 pb-3">
                  <div>
                    <div className="text-lg font-semibold text-primary">{selectedEntryPath || 'Sélectionne une entrée'}</div>
                    <div className="text-sm text-muted-foreground">
                      {selectedWorkspaceEntry?.is_dir
                        ? 'Dossier sélectionné. Tu peux le renommer, le déplacer ou le supprimer.'
                        : activeFile
                          ? `${getLanguage(activeFile.name)} • ${workspaceInfo?.project_dir || 'workspace projet'}`
                          : 'Ouvre un fichier pour commencer à éditer.'}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      className="gap-2 text-destructive hover:text-destructive"
                      disabled={!selectedEntryPath || loadingFilePath === selectedEntryPath || savingWorkspaceFile || creatingWorkspaceEntry}
                      onClick={handleDeleteWorkspaceEntry}
                    >
                      <Trash2 className="h-4 w-4" />
                      Supprimer
                    </Button>
                    <Button
                      type="button"
                      className="gap-2"
                      disabled={!activeFile || !activeFile.isDirty || savingWorkspaceFile}
                      onClick={handleSaveWorkspaceFile}
                    >
                      {savingWorkspaceFile ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                      Enregistrer
                    </Button>
                  </div>
                </div>
                <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
                  <div className="mb-2 text-[10px] font-bold uppercase tracking-[0.24em] text-muted-foreground">Renommer / déplacer</div>
                  <div className="flex gap-2">
                    <input
                      value={workspaceMovePath}
                      onChange={(event) => setWorkspaceMovePath(event.target.value)}
                      placeholder="nouveau/chemin"
                      disabled={!selectedEntryPath || creatingWorkspaceEntry}
                      className="h-10 flex-1 rounded-xl border border-border/60 bg-background px-3 text-sm outline-none focus:ring-1 focus:ring-primary"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      disabled={!selectedEntryPath || !workspaceMovePath.trim() || workspaceMovePath.trim() === selectedEntryPath || creatingWorkspaceEntry}
                      onClick={handleMoveWorkspaceEntry}
                    >
                      Renommer
                    </Button>
                  </div>
                </div>
              </div>

              <div className="flex min-h-0 flex-1 flex-col">
                <div className="flex overflow-x-auto border-b border-border/40 bg-black/20">
                  {openFiles.map((file, index) => (
                    <button
                      key={file.path}
                      type="button"
                      onClick={() => {
                        setActiveFileIndex(index);
                        setSelectedEntryPath(file.path);
                        setWorkspaceMovePath(file.path);
                      }}
                      className={cn(
                        'flex min-w-[160px] max-w-[260px] items-center gap-2 border-r border-border/40 px-4 py-3 text-xs font-medium transition-all',
                        activeFileIndex === index
                          ? 'bg-white/5 text-white border-b-2 border-b-primary'
                          : 'text-muted-foreground hover:bg-white/5 hover:text-foreground'
                      )}
                    >
                      <FileCode className={cn('h-3.5 w-3.5 shrink-0', activeFileIndex === index ? 'text-primary' : 'text-muted-foreground')} />
                      <span className="truncate flex-1 text-left">{file.name}</span>
                      {file.isDirty && <span className="h-2 w-2 rounded-full bg-primary shrink-0" />}
                      <X className="h-3.5 w-3.5 shrink-0 opacity-50 hover:opacity-100" onClick={(event) => closeFile(index, event)} />
                    </button>
                  ))}
                </div>

                <div className="min-h-0 flex-1">
                  {selectedWorkspaceEntry?.is_dir ? (
                    <div className="flex h-full items-center justify-center p-8 text-center text-muted-foreground">
                      <div className="space-y-3">
                        <Folder className="mx-auto h-10 w-10 text-primary/60" />
                        <p>Dossier sélectionné. Ouvre un fichier ou crée-en un nouveau pour commencer à éditer.</p>
                      </div>
                    </div>
                  ) : activeFile ? (
                    <Editor
                      height="100%"
                      theme="vs-dark"
                      language={getLanguage(activeFile.name)}
                      value={activeFile.content}
                      onChange={handleEditorChange}
                      onMount={(editor) => { editorRef.current = editor; }}
                      options={{
                        minimap: { enabled: true },
                        fontSize: 13,
                        lineNumbers: 'on',
                        roundedSelection: true,
                        scrollBeyondLastLine: false,
                        automaticLayout: true,
                        padding: { top: 14 },
                        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                        smoothScrolling: true,
                        cursorSmoothCaretAnimation: 'on',
                      }}
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center p-10 text-center text-muted-foreground">
                      <div className="space-y-4">
                        <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-[2rem] bg-primary/10 text-primary/50">
                          <FileCode className="h-10 w-10" />
                        </div>
                        <div>
                          <h3 className="text-lg font-semibold text-foreground">Cloud Workspace</h3>
                          <p className="mt-2 max-w-sm text-sm text-muted-foreground">
                            Ouvre plusieurs fichiers dans des onglets, modifie-les avec coloration syntaxique,
                            puis enregistre directement dans le workspace réel du projet.
                          </p>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-between border-t border-border/40 px-4 py-2 text-[10px] font-bold uppercase tracking-[0.24em] text-muted-foreground">
                  <div className="flex items-center gap-4">
                    <span>{activeFile ? getLanguage(activeFile.name) : 'idle'}</span>
                    <span>UTF-8</span>
                    {activeFile?.isDirty ? <span className="text-amber-400">Modifié</span> : null}
                    {loadingFilePath ? <span className="text-primary">Chargement...</span> : null}
                  </div>
                  <span className="truncate">{activeFile?.path || selectedEntryPath || 'Aucune sélection'}</span>
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>

      <button
        type="button"
        onClick={() => setTeamDrawerOpen(true)}
        className={cn(
          'fixed right-0 top-1/2 z-40 -translate-y-1/2 rounded-l-2xl border border-r-0 border-primary/30 bg-primary text-primary-foreground shadow-2xl shadow-primary/20 transition-transform hover:-translate-x-1',
          teamDrawerOpen && 'translate-x-full'
        )}
        title="Ouvrir l'équipe et les logs"
      >
        <span className="flex items-center gap-2 px-3 py-4 [writing-mode:vertical-rl]">
          <PanelRightOpen className="h-4 w-4 rotate-90" />
          <span className="text-xs font-bold uppercase tracking-widest">Équipe</span>
        </span>
      </button>

      {teamDrawerOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/45 backdrop-blur-[2px]"
            onClick={() => setTeamDrawerOpen(false)}
          />
          <aside className="fixed bottom-0 right-0 top-0 z-50 flex w-full max-w-[540px] flex-col border-l border-border bg-background/95 shadow-2xl shadow-black/40 backdrop-blur-xl">
            <div className="flex shrink-0 items-center justify-between border-b border-border/60 p-5">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-primary">Workspace live</p>
                <h2 className="mt-1 text-xl font-bold">Équipe, chat & logs</h2>
              </div>
              <Button variant="ghost" size="icon" onClick={() => setTeamDrawerOpen(false)}>
                <X className="h-5 w-5" />
              </Button>
            </div>

            <div className="grid min-h-0 flex-1 grid-rows-[220px_minmax(0,1fr)_240px] gap-4 overflow-hidden p-4">
              <Card className="flex min-h-0 flex-col overflow-hidden border-border/60 bg-muted/20">
                <CardHeader className="shrink-0 pb-3">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Users className="h-4 w-4 text-primary" />
                    Employés & statut
                  </CardTitle>
                  <CardDescription>
                    Vue rapide des équipes pendant la phase applicative.
                  </CardDescription>
                </CardHeader>
                <CardContent className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-3">
                  {employeeRoster.map((employee) => (
                    <div key={`${employee.avatar}-${employee.name}`} className="flex items-center justify-between rounded-xl border border-border/60 bg-background/60 px-3 py-2">
                      <div className="min-w-0">
                        <div className="font-semibold">{employee.name}</div>
                        <div className="truncate text-xs text-muted-foreground">{employee.role}</div>
                      </div>
                      <span
                        className={cn(
                          'rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-widest',
                          runningAgents[employee.agent]
                            ? 'border-primary/30 bg-primary/10 text-primary'
                            : 'border-border/60 bg-muted/30 text-muted-foreground'
                        )}
                      >
                        {agentStatuses[employee.agent] || (runningAgents[employee.agent] ? 'Travaille' : 'Disponible')}
                      </span>
                    </div>
                  ))}
                </CardContent>
              </Card>

              <Card className="flex min-h-0 flex-col overflow-hidden border-border/60 bg-muted/20">
                <CardHeader className="shrink-0 pb-3">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Bot className="h-4 w-4 text-primary" />
                    Chat des employés
                  </CardTitle>
                  <CardDescription>
                    Demande une nouvelle fonctionnalité, une correction ou une contrainte aux équipes IA.
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
                  <div className="min-h-0 flex-1 space-y-3 overflow-y-auto rounded-2xl border border-border/60 bg-background/40 p-3 pr-4">
                    {conversation.length === 0 ? (
                      <div className="flex h-full items-center justify-center text-center text-sm text-muted-foreground">
                        Les échanges des employés s'afficheront ici dès que le workflow poussera des messages.
                      </div>
                    ) : conversation.map((item, index) => (
                      <div key={`${item.employee.avatar}-${index}`} className={cn(
                        'rounded-2xl border px-3 py-3',
                        item.kind === 'user'
                          ? 'border-sky-500/20 bg-sky-500/5'
                          : 'border-border/60 bg-background/60'
                      )}>
                        <div className="mb-1 flex items-center gap-2">
                          <span className="flex h-8 w-8 items-center justify-center rounded-xl border border-border/60 bg-background text-xs font-bold">
                            {item.employee.avatar}
                          </span>
                          <div className="min-w-0">
                            <div className="truncate font-semibold">{item.employee.name}</div>
                            <div className="truncate text-[11px] text-muted-foreground">{item.employee.role}</div>
                          </div>
                        </div>
                        <p className="whitespace-pre-wrap text-sm leading-6 text-zinc-200">{item.message}</p>
                      </div>
                    ))}
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <textarea
                      value={chatInput}
                      onChange={(event) => setChatInput(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' && !event.shiftKey) {
                          event.preventDefault();
                          void handleSendMessage();
                        }
                      }}
                      placeholder="Demander une fonctionnalité, une correction ou une précision..."
                      className="h-24 flex-1 resize-none rounded-2xl border border-border/60 bg-background px-4 py-3 text-sm outline-none focus:ring-1 focus:ring-primary"
                    />
                    <Button
                      type="button"
                      className="h-24 px-4"
                      disabled={sendingMessage || !chatInput.trim()}
                      onClick={handleSendMessage}
                    >
                      {sendingMessage ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                    </Button>
                  </div>
                </CardContent>
              </Card>

              <Card className="flex min-h-0 flex-col overflow-hidden border-border/60 bg-black">
                <CardHeader className="shrink-0 pb-3">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <TerminalSquare className="h-4 w-4 text-primary" />
                    Logs système
                  </CardTitle>
                  <CardDescription>
                    {implementationPipeline?.status ? `Pipeline: ${implementationPipeline.status}` : `Flux: ${wsStatus}`}
                  </CardDescription>
                </CardHeader>
                <CardContent className="min-h-0 flex-1 overflow-y-auto rounded-b-2xl bg-black pr-3 font-mono text-xs leading-6 text-zinc-300">
                  <div className="space-y-1 p-3">
                    {logs.length === 0 ? (
                      <div className="text-muted-foreground">Aucun log pour le moment.</div>
                    ) : logs.map((log, index) => (
                      <div
                        key={`${log.text}-${index}`}
                        className={cn(
                          log.type === 'success' && 'text-emerald-400',
                          log.type === 'error' && 'text-rose-400',
                          log.type === 'info' && 'text-primary',
                          log.type === 'system' && 'text-zinc-300'
                        )}
                      >
                        {log.text}
                      </div>
                    ))}
                    <div ref={logsEndRef} />
                  </div>
                </CardContent>
              </Card>
            </div>
          </aside>
        </>
      )}
    </div>
  );
}
