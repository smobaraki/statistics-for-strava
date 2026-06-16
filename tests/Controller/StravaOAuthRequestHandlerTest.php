<?php

namespace App\Tests\Controller;

use App\Controller\StravaOAuthRequestHandler;
use App\Domain\Strava\InsufficientStravaAccessTokenScopes;
use App\Domain\Strava\InvalidStravaAccessToken;
use App\Domain\Strava\Strava;
use App\Domain\Strava\StravaClientId;
use App\Tests\ContainerTestCase;
use PHPUnit\Framework\MockObject\MockObject;
use Spatie\Snapshots\MatchesSnapshots;
use Symfony\Component\HttpFoundation\RedirectResponse;
use Symfony\Component\HttpFoundation\Request;
use Twig\Environment;

class StravaOAuthRequestHandlerTest extends ContainerTestCase
{
    use MatchesSnapshots;

    private StravaOAuthRequestHandler $stravaOAuthRequestHandler;
    private MockObject $strava;

    public function testHandleWithValidAccessToken(): void
    {
        $this->strava
            ->expects($this->once())
            ->method('verifyAccessToken');

        $this->assertEquals(
            new RedirectResponse('/', \Symfony\Component\HttpFoundation\Response::HTTP_FOUND),
            $this->stravaOAuthRequestHandler->handle(new Request(
                query: [],
                request: [],
                attributes: [],
                cookies: [],
                files: [],
                server: [],
                content: [],
            ))
        );
    }

    public function testHandleWhenInsufficientScopes(): void
    {
        $this->strava
            ->expects($this->once())
            ->method('verifyAccessToken')
            ->willThrowException(new InsufficientStravaAccessTokenScopes());

        $this->assertMatchesHtmlSnapshot($this->stravaOAuthRequestHandler->handle(new Request(
            query: [],
            request: [],
            attributes: [],
            cookies: [],
            files: [],
            server: [],
            content: [],
        ))->getContent());
    }

    public function testHandleWhenInvalidAccessToken(): void
    {
        $this->strava
            ->expects($this->once())
            ->method('verifyAccessToken')
            ->willThrowException(new InvalidStravaAccessToken('Bridge connection failed'));

        $this->assertMatchesHtmlSnapshot($this->stravaOAuthRequestHandler->handle(new Request(
            query: [],
            request: [],
            attributes: [],
            cookies: [],
            files: [],
            server: [],
            content: [],
        ))->getContent());
    }

    public function testHandleOnRandomError(): void
    {
        $this->strava
            ->expects($this->once())
            ->method('verifyAccessToken')
            ->willThrowException(new \RuntimeException('OH NOWZ'));

        $this->assertMatchesHtmlSnapshot($this->stravaOAuthRequestHandler->handle(new Request(
            query: [],
            request: [],
            attributes: [],
            cookies: [],
            files: [],
            server: [],
            content: [],
        ))->getContent());
    }

    #[\Override]
    protected function setUp(): void
    {
        $this->stravaOAuthRequestHandler = new StravaOAuthRequestHandler(
            StravaClientId::fromString('client'),
            $this->strava = $this->createMock(Strava::class),
            $this->getContainer()->get(Environment::class),
        );
    }
}
