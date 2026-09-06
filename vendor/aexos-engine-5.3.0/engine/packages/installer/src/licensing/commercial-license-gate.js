'use strict';

const path = require('path');

const INSTALL_MODES = Object.freeze({
  LEGACY: 'legacy',
  ENFORCE: 'enforce',
});

class CommercialLicenseRequiredError extends Error {
  constructor(message, options = {}) {
    super(message);
    this.name = 'CommercialLicenseRequiredError';
    this.code = options.code || 'AEXOS_LICENSE_REQUIRED';
    this.recoverable = true;
  }
}

function loadCommercialConfig(packageRoot = path.resolve(__dirname, '..', '..', '..', '..')) {
  try {
    const packageJson = require(path.join(packageRoot, 'package.json'));
    const config = packageJson.aexosCommercial || {};
    const installMode = config.installMode || INSTALL_MODES.LEGACY;

    if (!Object.values(INSTALL_MODES).includes(installMode)) {
      throw new Error(`Unsupported aexosCommercial.installMode: ${installMode}`);
    }

    return {
      installMode,
      purchaseUrl: config.purchaseUrl || 'https://cyryxlabs.com/aexos',
      supportUrl: config.supportUrl || 'https://cyryxlabs.com/contact',
    };
  } catch (error) {
    if (error instanceof CommercialLicenseRequiredError) {
      throw error;
    }
    throw new Error(`Unable to load AEXOS commercial configuration: ${error.message}`);
  }
}

function resolveCredentialOptions(options = {}, env = process.env) {
  return {
    key: options.licenseKey || env.AEXOS_LICENSE_KEY || env.AEXOS_PRO_KEY,
    email: options.licenseEmail || env.AEXOS_LICENSE_EMAIL || env.AEXOS_PRO_EMAIL,
    password: options.licensePassword || env.AEXOS_LICENSE_PASSWORD || env.AEXOS_PRO_PASSWORD,
  };
}

function redactCredentialValues(message, credentials) {
  let safeMessage = String(message || '');
  for (const value of Object.values(credentials || {})) {
    if (typeof value === 'string' && value.length > 0) {
      safeMessage = safeMessage.split(value).join('[REDACTED]');
    }
  }
  return safeMessage;
}

async function enforceCommercialInstallGate(options = {}) {
  const config = options.config || loadCommercialConfig(options.packageRoot);

  if (config.installMode !== INSTALL_MODES.ENFORCE) {
    return {
      required: false,
      admitted: true,
      mode: config.installMode,
    };
  }

  const runLicenseWizard = options.runLicenseWizard || require('../wizard/pro-setup').runProWizard;
  const credentials = resolveCredentialOptions(options, options.env || process.env);
  const targetDir = path.resolve(options.targetDir || process.cwd());

  let result;
  try {
    result = await runLicenseWizard({
      targetDir,
      key: credentials.key,
      email: credentials.email,
      password: credentials.password,
      quiet: Boolean(options.quiet),
      force: Boolean(options.force),
    });
  } catch (error) {
    const safeReason = redactCredentialValues(error.message, credentials);
    throw new CommercialLicenseRequiredError(
      `AEXOS license validation could not complete. ${safeReason} Purchase: ${config.purchaseUrl} Support: ${config.supportUrl}`,
      { code: 'AEXOS_LICENSE_VALIDATION_ERROR' },
    );
  }

  if (!result || result.success !== true || result.licenseValidated !== true) {
    const reason =
      result && result.error ? ` ${redactCredentialValues(result.error, credentials)}` : '';
    throw new CommercialLicenseRequiredError(
      `A paid AEXOS license is required before installation.${reason} Purchase: ${config.purchaseUrl} Support: ${config.supportUrl}`,
    );
  }

  return {
    required: true,
    admitted: true,
    mode: config.installMode,
    result,
  };
}

module.exports = {
  CommercialLicenseRequiredError,
  INSTALL_MODES,
  enforceCommercialInstallGate,
  loadCommercialConfig,
  redactCredentialValues,
  resolveCredentialOptions,
};
