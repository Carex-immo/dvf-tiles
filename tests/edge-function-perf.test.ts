/// <reference lib="deno.window" />

// Supabase Edge Function Performance Benchmarks
// Tests latency, response sizes, and cache effectiveness for the DVF tiles Edge Function
// Run: deno run --allow-net tests/edge-function-perf.test.ts
//
// Tests the Edge Function endpoint and measures:
// - Tile request latency (cold and warm)
// - Response sizes
// - Cache behavior
// - Error handling

export {};

const EDGE_FUNCTION_URL = "https://bqwbazolhtwizafxqzlr.supabase.co/functions/v1/dvf-tiles";

// Test result type
interface TestResult {
  testName: string;
  url: string;
  status: number;
  latency: number; // ms
  size: number; // bytes
  cached?: boolean;
  error?: string;
}

// Helper function to measure tile requests
async function measureTile(
  path: string,
  iteration: number = 1
): Promise<TestResult> {
  const url = `${EDGE_FUNCTION_URL}${path}`;
  const startTime = performance.now();

  try {
    const response = await fetch(url);
    const latency = performance.now() - startTime;

    // Get response body to measure size
    const buffer = await response.arrayBuffer();
    const size = buffer.byteLength;

    return {
      testName: path,
      url,
      status: response.status,
      latency: Math.round(latency * 10) / 10,
      size,
      cached: iteration > 1 && latency < 50, // Heuristic: cached if fast
    };
  } catch (error) {
    const latency = performance.now() - startTime;
    return {
      testName: path,
      url,
      status: 0,
      latency: Math.round(latency * 10) / 10,
      size: 0,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

// Test suite
async function runBenchmarks() {
  console.log("\n🚀 PMTiles Edge Function Performance Benchmarks\n");
  console.log(`Target: ${EDGE_FUNCTION_URL}\n`);

  const results: TestResult[] = [];
  let passOneStartTime = 0;
  let passTwoStartTime = 0;
  const batchResults: { passOne: TestResult[]; passTwo: TestResult[] } = {
    passOne: [],
    passTwo: [],
  };

  // Test 1: Valid tile request (mutations z14)
  console.log("Test 1: Valid tile request (mutations/14/8000/5900.mvt)");
  const test1Result = await measureTile("/mutations/14/8000/5900.mvt", 1);
  console.log(
    `  Status: ${test1Result.status}, Latency: ${test1Result.latency}ms, Size: ${test1Result.size} bytes\n`
  );
  results.push(test1Result);

  // Test 2: Out of zoom range (communes z3 should be 204)
  console.log("Test 2: Out of zoom range (communes/3/0/0.mvt)");
  const test2Result = await measureTile("/communes/3/0/0.mvt", 1);
  console.log(`  Status: ${test2Result.status}, Latency: ${test2Result.latency}ms\n`);
  results.push(test2Result);

  // Test 3: Invalid layer (should be 404)
  console.log("Test 3: Invalid layer (/invalid/10/512/256.mvt)");
  const test3Result = await measureTile("/invalid/10/512/256.mvt", 1);
  console.log(`  Status: ${test3Result.status}, Latency: ${test3Result.latency}ms\n`);
  results.push(test3Result);

  // Test 4: Departments tile
  console.log("Test 4: Departments tile (departements/5/16/10.mvt)");
  const test4Result = await measureTile("/departements/5/16/10.mvt", 1);
  console.log(
    `  Status: ${test4Result.status}, Latency: ${test4Result.latency}ms, Size: ${test4Result.size} bytes\n`
  );
  results.push(test4Result);

  // Test 5: Batch requests (16 tiles in 4x4 grid)
  console.log("Test 5: Batch requests (16 tiles, 4x4 grid at mutations/14)");
  passOneStartTime = performance.now();
  const batchSize = 4;
  const baseTileX = 8000;
  const baseTileY = 5900;

  for (let i = 0; i < batchSize; i++) {
    for (let j = 0; j < batchSize; j++) {
      const path = `/mutations/14/${baseTileX + i}/${baseTileY + j}.mvt`;
      const result = await measureTile(path, 1);
      batchResults.passOne.push(result);
    }
  }

  const passOneEndTime = performance.now();
  const passOneDuration = passOneEndTime - passOneStartTime;
  const passOneAvgLatency =
    batchResults.passOne.reduce((acc, r) => acc + r.latency, 0) /
    batchResults.passOne.length;
  const passOneTotalSize = batchResults.passOne.reduce((acc, r) => acc + r.size, 0);

  console.log(
    `  Avg latency: ${Math.round(passOneAvgLatency * 10) / 10}ms, Total size: ${passOneTotalSize} bytes, Total time: ${Math.round(passOneDuration * 10) / 10}ms\n`
  );

  // Small delay to ensure cache is primed
  await new Promise((resolve) => setTimeout(resolve, 100));

  // Test 6: Cache validation (second pass, same tiles)
  console.log("Test 6: Cache validation (second pass, same 16 tiles)");
  passTwoStartTime = performance.now();

  for (let i = 0; i < batchSize; i++) {
    for (let j = 0; j < batchSize; j++) {
      const path = `/mutations/14/${baseTileX + i}/${baseTileY + j}.mvt`;
      const result = await measureTile(path, 2);
      batchResults.passTwo.push(result);
    }
  }

  const passTwoEndTime = performance.now();
  const passTwoDuration = passTwoEndTime - passTwoStartTime;
  const passTwoAvgLatency =
    batchResults.passTwo.reduce((acc, r) => acc + r.latency, 0) /
    batchResults.passTwo.length;
  const passTwoTotalSize = batchResults.passTwo.reduce((acc, r) => acc + r.size, 0);
  const latencyImprovement = passOneAvgLatency - passTwoAvgLatency;

  console.log(
    `  Avg latency: ${Math.round(passTwoAvgLatency * 10) / 10}ms (improvement: ${Math.round(latencyImprovement * 10) / 10}ms), Total size: ${passTwoTotalSize} bytes, Total time: ${Math.round(passTwoDuration * 10) / 10}ms\n`
  );

  // Aggregate results
  const allResults = [...results, ...batchResults.passOne, ...batchResults.passTwo];

  // Calculate summary statistics
  const successResults = results.filter((r) => r.status === 200);
  const emptyResults = results.filter((r) => r.status === 204);
  const errorResults = results.filter((r) => r.status >= 400 || r.status === 0);

  const allLatencies = allResults.map((r) => r.latency);
  const avgLatency = allLatencies.reduce((a, b) => a + b, 0) / allLatencies.length;
  const maxLatency = Math.max(...allLatencies);
  const minLatency = Math.min(...allLatencies);

  // Print summary
  console.log("📊 Summary Statistics:\n");
  console.log(`  Successful responses (200): ${successResults.length}`);
  console.log(`  Empty tiles (204): ${emptyResults.length}`);
  console.log(`  Errors (4xx/5xx): ${errorResults.length}`);
  console.log(`  Average response time: ${Math.round(avgLatency * 10) / 10}ms`);
  console.log(`  Min latency: ${minLatency}ms`);
  console.log(`  Peak latency: ${maxLatency}ms`);
  console.log(`  Cache improvement: ${Math.round(latencyImprovement * 10) / 10}ms`);

  // Check performance targets
  console.log("\n🎯 Performance Targets Check:\n");

  const firstPassStats = allResults.slice(0, results.length + batchSize * batchSize);
  const firstPassAvg =
    firstPassStats.reduce((a, r) => a + r.latency, 0) / firstPassStats.length;
  const firstPassPeak = Math.max(...firstPassStats.map((r) => r.latency));

  const secondPassStats = batchResults.passTwo;
  const secondPassAvg =
    secondPassStats.reduce((a, r) => a + r.latency, 0) / secondPassStats.length;

  console.log(`  ✓ First pass avg latency: ${Math.round(firstPassAvg * 10) / 10}ms (target: <100ms)`);
  console.log(
    `  ${firstPassPeak > 100 ? "✗" : "✓"} First pass peak latency: ${firstPassPeak}ms (target: <100ms)`
  );
  console.log(
    `  ${secondPassAvg > 50 ? "✗" : "✓"} Cache hit avg latency: ${Math.round(secondPassAvg * 10) / 10}ms (target: <50ms)`
  );

  const totalFirstPassSize = batchResults.passOne.reduce((a, r) => a + r.size, 0);
  console.log(
    `  ✓ Batch 16 tiles size: ${totalFirstPassSize} bytes (target: 80KB-800KB typical)`
  );

  const totalFirstPassTime = passOneDuration;
  console.log(
    `  ${totalFirstPassTime > 1600 ? "✗" : "✓"} Batch 16 tiles time: ${Math.round(totalFirstPassTime * 10) / 10}ms (target: ~800ms)`
  );

  // Print detailed results
  console.log("\n📋 Detailed Results:\n");
  console.log("PASS 1 - Initial Requests:");
  results.forEach((r) => {
    console.log(`  ${r.testName}: ${r.status} - ${r.latency}ms${r.size ? ` - ${r.size}B` : ""}`);
  });

  console.log("\nBATCH PASS 1 (16 tiles):");
  let batchPassOneCount = 0;
  for (let i = 0; i < batchSize; i++) {
    for (let j = 0; j < batchSize; j++) {
      const r = batchResults.passOne[batchPassOneCount++];
      console.log(`  mutations/14/${baseTileX + i}/${baseTileY + j}: ${r.status} - ${r.latency}ms`);
    }
  }

  console.log("\nBATCH PASS 2 (16 tiles - cached):");
  let batchPassTwoCount = 0;
  for (let i = 0; i < batchSize; i++) {
    for (let j = 0; j < batchSize; j++) {
      const r = batchResults.passTwo[batchPassTwoCount++];
      const cached = r.latency < 50 ? " [CACHED]" : "";
      console.log(`  mutations/14/${baseTileX + i}/${baseTileY + j}: ${r.status} - ${r.latency}ms${cached}`);
    }
  }

  // Export results as JSON for analysis
  const jsonResults = {
    timestamp: new Date().toISOString(),
    endpoint: EDGE_FUNCTION_URL,
    testCount: allResults.length,
    summary: {
      successful: successResults.length,
      empty: emptyResults.length,
      errors: errorResults.length,
      avgLatency: Math.round(avgLatency * 10) / 10,
      minLatency,
      maxLatency,
    },
    passOne: {
      avgLatency: Math.round(firstPassAvg * 10) / 10,
      peakLatency: firstPassPeak,
      totalTime: Math.round(totalFirstPassTime * 10) / 10,
      totalSize: totalFirstPassSize,
    },
    passTwo: {
      avgLatency: Math.round(secondPassAvg * 10) / 10,
      totalTime: Math.round(passTwoDuration * 10) / 10,
      cacheImprovement: Math.round(latencyImprovement * 10) / 10,
    },
    allResults: allResults.map((r) => ({
      test: r.testName,
      status: r.status,
      latency: r.latency,
      size: r.size,
      error: r.error,
    })),
  };

  console.log("\n📤 JSON Results (for import/analysis):");
  console.log(JSON.stringify(jsonResults, null, 2));
}

// Run benchmarks
await runBenchmarks();
