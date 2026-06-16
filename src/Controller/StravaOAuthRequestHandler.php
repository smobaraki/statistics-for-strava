<?php

declare(strict_types=1);

namespace App\Controller;

use App\Domain\Strava\InsufficientStravaAccessTokenScopes;
use App\Domain\Strava\InvalidStravaAccessToken;
use App\Domain\Strava\Strava;
use App\Domain\Strava\StravaClientId;
use Symfony\Component\HttpFoundation\RedirectResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\HttpKernel\Attribute\AsController;
use Symfony\Component\Routing\Attribute\Route;
use Twig\Environment;

#[AsController]
final readonly class StravaOAuthRequestHandler
{
    public function __construct(
        private StravaClientId $stravaClientId,
        private Strava $strava,
        private Environment $twig,
    ) {
    }

    #[Route(path: '/strava-oauth', methods: ['GET'], priority: 2)]
    public function handle(Request $request): Response
    {
        try {
            $this->strava->verifyAccessToken();

            // Already authorized, load app.
            return new RedirectResponse('/', Response::HTTP_FOUND);
        } catch (\Exception $e) {
        }

        if ($e instanceof InsufficientStravaAccessTokenScopes) {
            return new Response($this->twig->render('html/strava-oauth/insufficient-scopes.html.twig', [
                'stravaClientId' => $this->stravaClientId,
                'returnUrl' => $request->getSchemeAndHttpHost().'/strava-oauth',
            ]), Response::HTTP_OK);
        }

        if ($e instanceof InvalidStravaAccessToken) {
            // Display a simple error page showing the connection issue.
            return new Response($this->twig->render('html/strava-oauth/error-page.html.twig', [
                'error' => $e->getMessage(),
            ]), Response::HTTP_OK);
        }

        return new Response($this->twig->render('html/strava-oauth/error-page.html.twig', [
            'error' => $e->getMessage(),
        ]), Response::HTTP_OK);
    }
}
