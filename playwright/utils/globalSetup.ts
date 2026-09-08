import { STORAGE_DIR, getDetectedUsers, logPlaywrightTestInfo } from './setup';
import * as fs from 'fs';
import * as os from 'os';

async function globalSetup() {
  console.log('🛠 Running global setup...');

  // Ensure storage directory exists
  if (!fs.existsSync(STORAGE_DIR)) {
    console.warn(`⚠️ STORAGE_DIR does not exist: ${STORAGE_DIR}. Creating...`);
    fs.mkdirSync(STORAGE_DIR, { recursive: true });
  }

  // Log detected users dynamically
  const detectedUsers = getDetectedUsers();
  console.log(`👥 Users detected after setup: ${detectedUsers.length > 0 ? 'Yes' : 'No'}`);

  // Log system capabilities
  const cpuCores = os.cpus().length;
  const totalMemory = os.totalmem() / (1024 ** 3); // Convert bytes to GB (binary-based)
  const roundedMemory = Math.ceil(totalMemory); // Round up to nearest integer
  console.log(`🖥 Adjusted for: ${cpuCores} CPU cores, ${roundedMemory} GB RAM`);

  // Log browser family being used
  const browserFamily = process.env.PLAYWRIGHT_BROWSER || 'chromium';
  console.log(`🌐 Running tests for browser family: ${browserFamily}`);

  // Log other test details
  logPlaywrightTestInfo();
}

export default globalSetup;