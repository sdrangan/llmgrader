% Parameters
lam = 1;        % Exp(theta)
wvar = 0.1;     % noise variance
nx = 200;       % number of points
x = linspace(-2,3,nx)'; % points to test

% ML estimate
xml = max(0,x);

% MAP estimate
t = wvar/lam;
mu = x-t;
xmap = max(0, mu);

% Compute MMSE estimate
u = -mu/sqrt(wvar);
phiu = 1/sqrt(2*pi)*exp(-u.^2/2);
xmmse = mu + sqrt(wvar)*phiu./qfunc(u);

% Plot the results
plot(x,[xml xmap xmmse],'-','Linewidth',2);
grid on;
set(gca,'FontSize',16);
legend('ML','MAP','MMSE','Location','NorthWest');
xlabel('x');
ylabel('thetaHat');
print -dpng softThresh;

