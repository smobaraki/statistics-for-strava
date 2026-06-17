<?php

declare(strict_types=1);

namespace App\Controller;

use App\Application\Import\StravaImport\ImportActivities\ImportActivities;
use App\Application\Import\StravaImport\ImportAthlete\ImportAthlete;
use App\Infrastructure\CQRS\Command\CommandBus;
use Symfony\Component\Console\Output\NullOutput;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\HttpKernel\Attribute\AsController;
use Symfony\Component\Routing\Attribute\Route;

#[AsController]
final readonly class TriggerImportController
{
    public function __construct(
        private CommandBus $commandBus,
    ) {
    }

    #[Route(path: '/api/trigger-import', methods: ['GET', 'POST'])]
    public function handle(): JsonResponse
    {
        set_time_limit(600);

        try {
            $output = new NullOutput();
            $this->commandBus->dispatch(new ImportAthlete($output));
            $this->commandBus->dispatch(new ImportActivities($output, null));

            return new JsonResponse(['status' => 'ok'], Response::HTTP_OK);
        } catch (\Exception $e) {
            return new JsonResponse(['status' => 'error', 'message' => $e->getMessage()], Response::HTTP_INTERNAL_SERVER_ERROR);
        }
    }
}
