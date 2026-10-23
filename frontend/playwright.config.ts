import {defineConfig} from "@playwright/test";
export default defineConfig({testDir:"./tests/e2e",timeout:45000,fullyParallel:false,workers:1,retries:0,reporter:"list",use:{baseURL:process.env.PW_BASE_URL??"http://localhost:8000",browserName:"chromium",headless:true,reducedMotion:"reduce",trace:"retain-on-failure"},outputDir:"../data/playwright-results"});
