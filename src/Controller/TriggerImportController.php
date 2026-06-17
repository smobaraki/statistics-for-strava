<?php

declare(strict_types=1);

namespace App\Controller;

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\HttpKernel\Attribute\AsController;
use Symfony\Component\Process\Process;
use Symfony\Component\Routing\Attribute\Route;

#[AsController]
final class TriggerImportController
{
    #[Route(path: '/api/trigger-import', methods: ['GET', 'POST'], priority: 10)]
    public function handle(): JsonResponse
    {
        set_time_limit(600);

        $projectDir = $_ENV['APP_PROJECT_DIR'] ?? '/var/www';

        try {
            $process = new Process(['php', $projectDir.'/bin/console', 'app:cron:run-strava-import']);
            $process->setWorkingDirectory($projectDir);
            $process->setTimeout(600);
            $process->run();

            if ($process->isSuccessful()) {
                return new JsonResponse(['status' => 'ok', 'output' => substr($process->getOutput(), -500)], Response::HTTP_OK);
            }

            return new JsonResponse(['status' => 'error', 'message' => $process->getErrorOutput() ?: $process->getOutput()], Response::HTTP_INTERNAL_SERVER_ERROR);
        } catch (\Exception $e) {
            return new JsonResponse(['status' => 'error', 'message' => $e->getMessage()], Response::HTTP_INTERNAL_SERVER_ERROR);
        }
    }
}
