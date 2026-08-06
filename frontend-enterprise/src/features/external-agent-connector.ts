const configuredRef = import.meta.env.VITE_EXTERNAL_AGENT_CONNECTOR_REF?.trim();

/**
 * The connector is an independently released project. Production deployments
 * can override VITE_EXTERNAL_AGENT_CONNECTOR_REF with a newer audited immutable
 * tag or SHA. The built-in fallback is the first independently released tag.
 */
export const CONNECTOR_REPOSITORY = 'KaiGongBa/kaigongba-agent-connector';
export const CONNECTOR_REF = configuredRef || 'v0.7.1';
export const CONNECTOR_REF_IS_PINNED = /^(?:[0-9a-f]{40}|v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)$/.test(CONNECTOR_REF);
export const CONNECTOR_SOURCE_URL = `https://github.com/${CONNECTOR_REPOSITORY}/tree/${encodeURIComponent(CONNECTOR_REF)}`;
export const CONNECTOR_INSTALL_COMMAND = `python3 -m pip install "git+https://github.com/${CONNECTOR_REPOSITORY}.git@${CONNECTOR_REF}"`;

export function connectorCommands(input: {
  baseUrl: string;
  enrollmentId: string;
  transport: 'polling' | 'webhook' | 'a2a' | 'manual';
}) {
  const profile = `external-${input.enrollmentId}`;
  const agentName = '我的外接员工';
  const previewPath = '/path/to/manifest-preview.json';
  const confirmedPath = '/path/to/manifest-confirmed.json';
  const reviewedDigest = 'sha256:reviewed-preview-digest';
  return {
    plan: 'kaigongba-agent assist route --intent connect',
    discoverPreview: [
      'kaigongba-agent discover preview',
      '--approved-root /path/to/approved-skills',
      `--agent-id ${shellQuote(profile)}`,
      `--agent-name ${shellQuote(agentName)}`,
      `--agent-description ${shellQuote('用户授权的外接 AI 员工')}`,
      `--output ${previewPath}`,
    ].join(' '),
    discoverConfirm: [
      'kaigongba-agent discover confirm',
      `--preview ${previewPath}`,
      `--digest ${reviewedDigest}`,
      `--output ${confirmedPath}`,
    ].join(' '),
    enroll: [
      'kaigongba-agent register enroll',
      `--base-url ${shellQuote(input.baseUrl)}`,
      `--profile ${shellQuote(profile)}`,
      '--provider codex',
      '--runtime-type local',
      `--transport ${input.transport}`,
      `--external-agent-ref ${shellQuote(profile)}`,
      `--employee-name ${shellQuote(agentName)}`,
      '--confirm-store-credential',
    ].join(' '),
    manifest: `kaigongba-agent register manifest --profile ${shellQuote(profile)} --manifest ${confirmedPath} --confirm-submit-digest ${reviewedDigest}`,
  };
}

export function externalAgentReviewPath(connectionId: string) {
  return `/enterprise/agents/external/${encodeURIComponent(connectionId)}/review`;
}

export function externalAgentNeedsSetup(status: string) {
  return !['available', 'manual_ready', 'disconnected'].includes(status);
}

function shellQuote(value: string) {
  return `'${value.replace(/'/g, `'"'"'`)}'`;
}
